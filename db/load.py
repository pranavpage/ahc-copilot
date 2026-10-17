"""Load one or more dataset folders into the copilot's SQLite database.

    python db/load.py                                  # test data -> data/copilot.db
    python db/load.py --sample --db data/sample.db     # sample data (the unit tests use it)
    python db/load.py --data A --data B --db other.db

Each data folder has the `sample-data/` layout (fleet/ and assets/). Loading is per well:
a well's source rows are replaced, so reloading or loading a dataset with more history for
the same wells is safe. Copilot-written rows (corrections, user rules, notes with
source='copilot', conversations) are never touched.
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
DATASET = ROOT / "flytbase-ahc-swe-asset-intelligence-dataset"
DEFAULT_DATA = DATASET / "test-data" / "dataset"
SAMPLE_DATA = DATASET / "sample-data"
SAMPLE_TODAY = "2026-10-16"
DEFAULT_DB = ROOT / "data" / "copilot.db"

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Rules parsed from the documents. Patterns run on normalised text (no ** markup,
# whitespace collapsed), one paragraph or one table row at a time.
# (rule_key, document kind, unit, pattern)
RULE_PATTERNS = [
    ("production_min_delta_c", "well_manual", "°C", r"producing \(active\)[^.]*? at least ([\d.]+) °C above ambient"),
    ("wellhead_alarm_max_c", "well_manual", "°C", r"at or below ([\d.]+) °C"),
    ("spill_shutin_pad_pct", "well_manual", "%", r"more than ([\d.]+) ?% of the pad"),
    ("rca_corrective_count", "well_manual", "repairs", r"(\w+) or more corrective|RCA after (\w+) corrective"),
    ("rca_window_months", "well_manual", "months", r"corrective[^.;]*?(?:in the|within) (\d+) months"),
    ("downtime_report_days", "well_manual", "days", r"(?:more than|over) (\d+) consecutive days"),
    ("spill_moderate_min_bbl", "sop", "bbl", r"^\| Moderate \| ([\d.]+) bbl"),
    ("spill_reportable_min_bbl", "sop", "bbl", r"^\| Reportable \| ([\d.]+) bbl"),
    ("spill_major_min_bbl", "sop", "bbl", r"^\| Major \| ([\d.]+) bbl"),
    ("hse_notice_hours", "sop", "hours", r"notify HSE within (\d+) ?h"),
    ("spill_notice_hours", "sop", "hours", r"written notice[^|]*? within (\d+) hours of discovery"),
    ("spill_notice_hours_major", "sop", "hours", r"or within (\d+) hours for a major"),
    ("containment_max_hours", "sop", "hours", r"contained within (\d+) hours"),
    ("cleanup_max_tph_pct", "sop", "% TPH", r"cleaned to ([\d.]+)% TPH or less"),
    ("cleanup_verification_days", "sop", "days", r"verified within (\d+) days"),
    ("inspection_max_interval_days", "sop", "days", r"at least once every (\d+) days"),
    ("nov_response_days", "sop", "days", r"answered within (\d+) days"),
    ("report_writeup_days", "sop", "days", r"maintenance report within (\d+) days"),
]

# Not in the fleet documents: stated in 02-dataset-guide.md.
GUIDE_RULES = [
    ("downtime_days_per_inspection", 7, "days",
     "Each well is inspected once a week, so every inspection in a period that finds the "
     "well not producing oil counts as 7 days of downtime."),
]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Operations SOP OPS-4: the first row with a keyword in the root-cause text wins.
FAILURE_CATEGORIES = [
    ("Installation error", ["installation", "installed incorrectly", "misaligned", "re-terminated",
                            "not torqued", "cross-threaded"]),
    ("Sand", ["sand"]),
    ("Scale", ["scale", "paraffin"]),
    ("Gas interference", ["gas lock", "gas interference", "free gas"]),
    ("Corrosion", ["corrosion", "corroded"]),
    ("Electrical", ["winding", "insulation", "switch", "terminal box"]),
    ("Fatigue/wear", ["fatigue", "wear", "worn", "years of service", "buckling", "ageing", "vibration"]),
]

# Operator notes (Operations SOP): what the note reports. Checked in this order.
NOTE_EVENTS = [
    ("gas_odor", r"gas odou?r|smell(?:ed)? gas|gas smell|rotten.egg|H2S monitor alarm"),
    ("bypass_out", r"bypass (?:removed|pulled)|took the bypass out|bypass out\b"),
    ("bypass_in", r"bypass (?:in place|installed)|put the bypass in|had the bypass installed"),
    ("shut_in", r"\bshut(?:-| )?in\b|shut the well in"),
    ("restart", r"\brestarted\b(?! from the panel)|back on production|back online"),
]
NOTE_SYMPTOMS = [
    ("rod squeal", r"squeal"), ("rattle", r"rattl"), ("fluid pound", r"fluid pound"),
    ("tagging bottom", r"tagging bottom"), ("amps hunting", r"amps hunting"),
    ("drive tripping", r"tripping"), ("leak", r"leak(?:ing)? at|found .* leaking|leak suspected"),
]

WAIT_REASONS = [
    ("parts", r"back-ordered|part"), ("weather", r"rain|weather|snow|ice|road"),
    ("contractor", r"contractor"), ("rig", r"workover rig"), ("crew", r"crew"),
]
WAIT_RE = re.compile(r"for about ([\d.]+) days? longer than the repair itself because ([^.]+)\.", re.I)
PARTS_RE = re.compile(r"\*\*Parts installed:\*\*\s*(.+?) pump, serial (\S+), lot ([\w-]+)")
FOLLOW_UP_RE = re.compile(r"\*\*Follow-up:\*\*\s*(.+)")
H2S_RE = re.compile(r"highest reading ([\d.]+) ppm", re.I)
TODAY_RE = re.compile(r'"Today" is (\d{1,2}) (\w{3})\w* (\d{4})')

CONTAINMENT_RE = re.compile(r"contained (?:about |within about |after about )?([\d.]+) hours?", re.I)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def strip_md(text):
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()


def split_sections(md, max_level):
    """Split markdown at headings up to max_level. Returns [(level, heading, body)]."""
    sections, level, heading, body = [], 0, "", []
    for line in md.splitlines():
        m = re.match(r"^(#{1,%d}) (.+)$" % max_level, line)
        if m:
            if heading or "".join(body).strip():
                sections.append((level, heading, "\n".join(body).strip()))
            level, heading, body = len(m.group(1)), m.group(2).strip(), []
        else:
            body.append(line)
    sections.append((level, heading, "\n".join(body).strip()))
    return sections


def blocks(body):
    """Paragraphs (collapsed) and table rows (one each), for rule matching."""
    out, para = [], []
    for line in body.splitlines():
        if line.lstrip().startswith("|"):
            if para:
                out.append(strip_md(" ".join(para)))
                para = []
            out.append(strip_md(line))
        elif not line.strip():
            if para:
                out.append(strip_md(" ".join(para)))
                para = []
        else:
            para.append(line)
    if para:
        out.append(strip_md(" ".join(para)))
    return out


def parse_date(text):
    """'30 Nov 2026' -> '2026-11-30' (None if no date)."""
    m = re.search(r"(\d{1,2}) (\w{3})\w* (\d{4})", text or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def failure_category(root_cause):
    text = (root_cause or "").lower()
    if not text:
        return None
    for category, words in FAILURE_CATEGORIES:
        if any(w in text for w in words):
            return category
    return "Other"


def note_event(text):
    """(event, symptom) for an operator note."""
    symptom = next((name for name, pat in NOTE_SYMPTOMS if re.search(pat, text, re.I)), None)
    for event, pat in NOTE_EVENTS:
        if re.search(pat, text, re.I):
            return event, symptom
    return ("symptom" if symptom else "routine"), symptom


def to_number(token):
    token = token.lower()
    return float(NUMBER_WORDS[token]) if token in NUMBER_WORDS else float(token)


class Loader:
    def __init__(self, conn, data_dir):
        self.c = conn
        self.data = data_dir
        self.warnings = []
        self.counts = {}

    def warn(self, msg):
        self.warnings.append(msg)

    def count(self, table, n=1):
        self.counts[table] = self.counts.get(table, 0) + n

    def rel(self, path):
        return str(path.relative_to(self.data))

    # ---------------------------------------------------------------- fleet

    def load_fleet(self):
        fleet = self.data / "fleet"
        areas = json.loads((fleet / "areas.json").read_text())
        for t in areas["teams"]:
            self.c.execute("INSERT OR REPLACE INTO teams VALUES (?,?,?)",
                           (t["team_id"], t["name"], t.get("lead_user_id")))
            self.count("teams")
        for a in areas["areas"]:
            center = a.get("center") or {}
            self.c.execute("INSERT OR REPLACE INTO areas VALUES (?,?,?,?,?)",
                           (a["area_id"], a["name"], a.get("team_id"), center.get("lat"), center.get("lon")))
            self.count("areas")
        self.area_members = {wid: a["area_id"] for a in areas["areas"] for wid in a.get("asset_ids", [])}

        for u in json.loads((fleet / "users.json").read_text())["users"]:
            self.c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)",
                           (u["user_id"], u["name"], u["role"], u.get("team_id")))
            self.count("users")

        docs = [(p, "well_manual", p.stem) for p in sorted((fleet / "well-types").glob("*.md"))]
        docs += [(p, "sop", None) for p in sorted((fleet / "sops").glob("*.md"))]
        for path, kind, well_type in docs:
            self.load_document(path, kind, well_type)
        self.load_mocs(sorted((fleet / "sops").glob("moc-*.md")))
        for path in sorted((fleet / "sops").glob("*recall*.md")):
            self.load_recall(path)

    def load_mocs(self, paths):
        """MOC memos -> moc_approvals. An extension memo ("This memo extends MOC-...")
        replaces the expiry date of the memo it extends."""
        memos = []
        for path in paths:
            md = strip_md(path.read_text())
            moc_id = re.search(r"MOC-\d{4}-\d{3}", path.read_text()).group(0)
            extends = re.search(r"extends (MOC-\d{4}-\d{3})", md)
            change = md.split("## Change", 1)[-1].split("## Conditions", 1)[0]
            memos.append({
                "moc_id": moc_id, "doc_id": path.stem,
                "title": (re.search(r"Title: (.+?) Date:", md) or [None, None])[1],
                "effective_from": parse_date((re.search(r"Effective from ([^.]+)\.", md) or [None, ""])[1]),
                "expiry": parse_date((re.search(r"approval expires on ([^.]+)\.", md) or [None, ""])[1]),
                "extends": extends.group(1) if extends else None,
                "wells": sorted(set(re.findall(r"WELL-\d{4}", change))),
            })
        self.c.execute("DELETE FROM moc_approvals")
        by_id = {m["moc_id"]: m for m in memos}
        for m in memos:
            if m["extends"]:
                continue
            ext = [e for e in memos if e["extends"] == m["moc_id"]]
            ext.sort(key=lambda e: e["expiry"] or "")
            last = ext[-1] if ext else None
            for wid in m["wells"]:
                self.c.execute("INSERT OR REPLACE INTO moc_approvals VALUES (?,?,?,?,?,?,?,?)", (
                    m["moc_id"], wid, m["title"], m["effective_from"], m["expiry"],
                    last["expiry"] if last else m["expiry"], last["moc_id"] if last else None, m["doc_id"]))
                self.count("moc_approvals")
            if not m["expiry"]:
                self.warn(f"{m['doc_id']}: no expiry date found")
        for m in memos:
            if m["extends"] and m["extends"] not in by_id:
                self.warn(f"{m['doc_id']}: extends {m['extends']}, which is not loaded")

    def load_recall(self, path):
        md = strip_md(path.read_text())
        ref = (re.search(r"Reference: (\S+)", md) or [None, None])[1]
        model = (re.search(r"Highline ([\w-]+) downhole", md) or [None, None])[1]
        recalled = md.split("What is recalled", 1)[-1].split("Pumps from all other lots", 1)[0]
        replace_by = parse_date((re.search(r"\(by ([^)]+)\)", md) or [None, ""])[1])
        for lot in sorted(set(re.findall(r"LOT-\d{4}-[A-Z]", recalled))):
            self.c.execute("INSERT OR REPLACE INTO recall_lots VALUES (?,?,?,?,?,?)", (
                lot, f"Highline {model}" if model else None, ref,
                parse_date((re.search(r"Date: ([^R]+?) Reference", md) or [None, ""])[1]),
                replace_by, path.stem))
            self.count("recall_lots")

    def load_document(self, path, kind, well_type):
        doc_id = path.stem
        md = path.read_text()
        title = next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), doc_id)
        self.c.execute("DELETE FROM doc_sections WHERE doc_id = ?", (doc_id,))
        self.c.execute("DELETE FROM search_fts WHERE kind = 'doc_section' AND ref_id = ?", (doc_id,))
        self.c.execute("DELETE FROM rules WHERE source = 'document' AND doc_id = ?", (doc_id,))
        self.c.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)",
                       (doc_id, kind, well_type, self.rel(path), title, md))
        self.count("documents")

        path_stack = {}
        found = set()
        for ord_, (level, heading, body) in enumerate(split_sections(md, 3)):
            path_stack = {k: v for k, v in path_stack.items() if k < level}
            path_stack[level] = heading
            section_path = " > ".join(path_stack[k] for k in sorted(path_stack) if k > 1) or heading
            self.c.execute("INSERT INTO doc_sections VALUES (?,?,?,?,?,?)",
                           (doc_id, ord_, level, heading, section_path, body))
            self.c.execute("INSERT INTO search_fts VALUES ('doc_section', ?, NULL, ?, ?)",
                           (doc_id, f"{title} — {section_path}", body))
            self.count("doc_sections")
            for block in blocks(body):
                for key, rule_kind, unit, pattern in RULE_PATTERNS:
                    if rule_kind != kind or key in found:
                        continue
                    m = re.search(pattern, block, re.I)
                    if not m:
                        continue
                    value = to_number(next(g for g in m.groups() if g))
                    proto = re.match(r"^\| ([A-Z]{2}-\d{2}) \|", block)
                    self.c.execute(
                        "INSERT INTO rules (rule_key, well_type, value, unit, source, doc_id, section_path,"
                        " protocol_id, source_text, created_at) VALUES (?,?,?,?, 'document', ?,?,?,?,?)",
                        (key, well_type, value, unit, doc_id, section_path,
                         proto.group(1) if proto else None, block[:400], now_iso()))
                    found.add(key)
                    self.count("rules")
        if kind == "well_manual":
            for key, rule_kind, _, _ in RULE_PATTERNS:
                if rule_kind == "well_manual" and key not in found:
                    self.warn(f"{doc_id}: rule {key} not found in manual")
        self.sop_rules_found = getattr(self, "sop_rules_found", set())
        if kind == "sop":
            self.sop_rules_found |= found

    def load_guide_rules(self):
        self.c.execute("DELETE FROM rules WHERE source = 'document' AND doc_id = '02-dataset-guide'")
        for key, value, unit, text in GUIDE_RULES:
            self.c.execute(
                "INSERT INTO rules (rule_key, value, unit, source, doc_id, section_path, source_text, created_at)"
                " VALUES (?,?,?, 'document', '02-dataset-guide', 'Inspections', ?, ?)",
                (key, value, unit, text, now_iso()))
            self.count("rules")
        for key, rule_kind, _, _ in RULE_PATTERNS:
            if rule_kind == "sop" and key not in self.sop_rules_found:
                self.warn(f"SOPs: rule {key} not found")

    # ---------------------------------------------------------------- wells

    def load_wells(self):
        well_dirs = sorted(p for p in (self.data / "assets").iterdir() if p.is_dir())
        for wdir in well_dirs:
            self.load_well(wdir)
        known = {r[0] for r in self.c.execute("SELECT asset_id FROM wells")}
        for wid in sorted(set(self.area_members) - known):
            self.warn(f"areas.json lists {wid} but no well folder was loaded")

    def clear_well(self, asset_id):
        c = self.c
        for sql in [
            "DELETE FROM search_fts WHERE asset_id = ? AND kind IN ('report_section', 'note', 'inspection_note')",
            "DELETE FROM report_compliance WHERE maintenance_id IN (SELECT maintenance_id FROM maintenance WHERE asset_id = ?)",
            "DELETE FROM report_sections WHERE maintenance_id IN (SELECT maintenance_id FROM maintenance WHERE asset_id = ?)",
            "DELETE FROM maintenance_reports WHERE asset_id = ?",
            "DELETE FROM corrections WHERE source = 'dataset' AND asset_id = ?",
            "DELETE FROM notes WHERE source = 'dataset' AND asset_id = ?",
            "DELETE FROM regulatory_events WHERE asset_id = ?",
            "DELETE FROM maintenance WHERE asset_id = ?",
            "DELETE FROM inspections WHERE asset_id = ?",
            "DELETE FROM equipment WHERE asset_id = ?",
            "DELETE FROM well_type_history WHERE asset_id = ?",
            "DELETE FROM team_history WHERE asset_id = ?",
        ]:
            c.execute(sql, (asset_id,))

    def load_well(self, wdir):
        c = self.c
        meta = json.loads((wdir / "metadata.json").read_text())
        wid = meta["asset_id"]
        self.clear_well(wid)

        loc, last = meta.get("location") or {}, meta.get("last_inspection") or {}
        c.execute("INSERT OR REPLACE INTO wells VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            wid, meta["name"], meta.get("asset_category"), meta["well_type"], meta.get("area_id"),
            meta.get("team_id"), meta.get("in_charge_user_id"), loc.get("lat"), loc.get("lon"),
            meta.get("installed_on"), meta.get("recorded_status"), last.get("inspection_id"),
            last.get("inspected_at"), last.get("inspector_user_id"),
            meta.get("status"), meta.get("decommissioned_on")))
        self.count("wells")
        for h in meta.get("type_history") or []:
            c.execute("INSERT OR REPLACE INTO well_type_history VALUES (?,?,?,?)",
                      (wid, h["well_type"], h["from"], h.get("to") or None))
        for h in meta.get("team_history") or []:
            c.execute("INSERT OR REPLACE INTO team_history VALUES (?,?,?,?)",
                      (wid, h["team_id"], h["from"], h.get("to") or None))
        if self.area_members.get(wid) not in (None, meta.get("area_id")):
            self.warn(f"{wid}: metadata area {meta.get('area_id')} != areas.json {self.area_members[wid]}")
        for e in meta.get("equipment", []):
            c.execute("INSERT OR REPLACE INTO equipment VALUES (?,?,?,?)",
                      (e["equipment_id"], wid, e["kind"], e.get("model")))
            self.count("equipment")

        for r in read_jsonl(wdir / "inspections.jsonl"):
            c.execute(
                "INSERT INTO inspections (inspection_id, asset_id, inspected_at, inspector_user_id, method,"
                " ambient_temp_c, wellhead_temp_c, spill_detected, spill_area_pct, spill_est_volume_bbl,"
                " evidence_images, notes, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["inspection_id"], wid, r["inspected_at"], r.get("inspector_user_id"), r.get("method"),
                 r.get("ambient_temp_c"), r.get("wellhead_temp_c"), int(bool(r.get("spill_detected"))),
                 r.get("spill_area_pct"), r.get("spill_est_volume_bbl"),
                 json.dumps(r.get("evidence_images") or []), r.get("notes") or "", r.get("recorded_at")))
            if r.get("notes"):
                c.execute("INSERT INTO search_fts VALUES ('inspection_note', ?, ?, ?, ?)",
                          (r["inspection_id"], wid, f"Inspection {r['inspection_id']} {r['inspected_at'][:10]}", r["notes"]))
            self.count("inspections")

        for r in read_jsonl(wdir / "maintenance.jsonl"):
            cost, rev = r.get("cost_usd") or {}, r.get("cost_revision") or {}
            c.execute("INSERT INTO maintenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                r["maintenance_id"], wid, r["started_at"], r.get("completed_at"), r["maintenance_type"],
                r.get("equipment_kind"), r.get("issue"), r.get("action_taken"), r.get("technician_user_id"),
                r.get("contractor"), r.get("downtime_hours"), cost.get("labor"), cost.get("parts"),
                cost.get("total"), r.get("triggered_by_inspection_id"), r.get("report_file"),
                r.get("recorded_at"), rev.get("original_total"), rev.get("revised_on"), rev.get("reason")))
            self.count("maintenance")
            if r.get("report_file"):
                self.load_report(wdir, wid, r["maintenance_id"], r["report_file"], r.get("issue") or "")

        for r in read_jsonl(wdir / "regulatory-events.jsonl"):
            c.execute("INSERT INTO regulatory_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                r["event_id"], wid, r["date"], r.get("agency"), r["event_type"], r.get("protocol_id"),
                r.get("related_inspection_id"), r.get("detail"), r.get("hours_to_report"),
                r.get("fine_usd"), r.get("status")))
            self.count("regulatory_events")

        for r in read_jsonl(wdir / "context.jsonl"):
            self.load_note(wid, r)

    def load_report(self, wdir, wid, mid, report_file, issue=""):
        path = wdir / report_file
        if not path.exists():
            self.warn(f"{mid}: report_file {report_file} not found")
            return
        md = path.read_text()
        sections = split_sections(md, 2)
        title = next((h for lvl, h, _ in sections if lvl == 1), mid)
        plain = md.replace("**", "")
        m = CONTAINMENT_RE.search(plain)
        root = next((b for lvl, h, b in sections if lvl == 2 and h.lower().startswith("root cause")), None)
        parts, follow = PARTS_RE.search(md), FOLLOW_UP_RE.search(md)
        wait, h2s = WAIT_RE.search(re.sub(r"\s+", " ", plain)), H2S_RE.search(plain)
        wait_reason = None
        if wait:
            wait_reason = next((k for k, pat in WAIT_REASONS if re.search(pat, wait.group(2), re.I)), "other")
        fdays = re.search(r"within (\d+) days", follow.group(1)) if follow else None
        fto = re.search(r"Follow-up to (MNT-[\w-]+?):", issue)
        is_spill = "spill clean-up" in md.lower()
        self.c.execute(
            "INSERT INTO maintenance_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                mid, wid, self.rel(path), title, md, float(m.group(1)) if m else None,
                int("interim report" in plain.lower()), root, failure_category(root),
                parts.group(0).split(":**", 1)[1].strip() if parts else None,
                parts.group(1) if parts else None, parts.group(2) if parts else None,
                parts.group(3) if parts else None,
                follow.group(1).strip() if follow else None, int(fdays.group(1)) if fdays else None,
                fto.group(1) if fto else None,
                float(wait.group(1)) if wait else None, wait_reason, wait.group(2).strip() if wait else None,
                float(h2s.group(1)) if h2s else None,
                int("Soil samples sent to the lab." in md) if is_spill else None))
        self.count("maintenance_reports")
        ord_ = 0
        for level, heading, body in sections:
            if level != 2:
                continue
            self.c.execute("INSERT INTO report_sections VALUES (?,?,?,?)", (mid, ord_, heading, body))
            self.c.execute("INSERT INTO search_fts VALUES ('report_section', ?, ?, ?, ?)",
                           (mid, wid, f"{mid} — {heading}", body))
            ord_ += 1
            if heading.lower().startswith("compliance check"):
                for row in body.splitlines():
                    cells = [strip_md(x) for x in row.strip().strip("|").split("|")]
                    if len(cells) < 2 or cells[0] in ("Protocol", "") or set(cells[0]) <= set("-: "):
                        continue
                    self.c.execute("INSERT OR REPLACE INTO report_compliance VALUES (?,?,?,?)",
                                   (mid, cells[0], cells[1], cells[2] if len(cells) > 2 else None))
                    self.count("report_compliance")

    def load_note(self, wid, r):
        event, symptom = note_event(r["text"]) if r["note_type"] == "operator_note" else (None, None)
        self.c.execute(
            "INSERT INTO notes (note_id, source, asset_id, created_at, author_user_id, note_type,"
            " inspection_id, text, valid_from, valid_to, event, symptom)"
            " VALUES (?, 'dataset', ?,?,?,?,?,?,?,?,?,?)",
            (r["note_id"], wid, r["created_at"], r.get("author_user_id"), r["note_type"],
             r.get("inspection_id"), r["text"], r.get("valid_from"), r.get("valid_to"), event, symptom))
        self.c.execute("INSERT INTO search_fts VALUES ('note', ?, ?, ?, ?)",
                       (r["note_id"], wid, f"Note {r['note_id']} ({r['note_type']})", r["text"]))
        self.count("notes")
        # Dataset guide: "A correction overrides the detection of the inspection named in
        # its inspection_id". Store it as a spill_detected override with provenance.
        if r["note_type"] == "correction":
            if not r.get("inspection_id"):
                self.warn(f"{r['note_id']}: correction note without inspection_id")
                return
            self.c.execute(
                "INSERT INTO corrections (correction_id, source, kind, target_table, target_id, asset_id,"
                " field, original_value, corrected_value, author_user_id, reason, created_at, note_id)"
                " VALUES (?, 'dataset', 'ai_analysis', 'inspections', ?, ?, 'spill_detected',"
                " (SELECT spill_detected FROM inspections WHERE inspection_id = ?), 0, ?, ?, ?, ?)",
                (f"COR-{r['note_id']}", r["inspection_id"], wid, r["inspection_id"],
                 r.get("author_user_id"), r["text"], r["created_at"], r["note_id"]))
            self.count("corrections")
        # Test data: a correction to one field of one inspection, with its values.
        elif r["note_type"] == "data_correction":
            if not (r.get("inspection_id") and r.get("field")):
                self.warn(f"{r['note_id']}: data_correction note without inspection_id or field")
                return
            kind = "ai_analysis" if r["field"].startswith("spill_") else "raw_data"
            self.c.execute(
                "INSERT INTO corrections (correction_id, source, kind, target_table, target_id, asset_id,"
                " field, original_value, corrected_value, author_user_id, reason, created_at, note_id)"
                " VALUES (?, 'dataset', ?, 'inspections', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"COR-{r['note_id']}", kind, r["inspection_id"], wid, r["field"], r.get("original_value"),
                 r.get("corrected_value"), r.get("author_user_id"), r["text"], r["created_at"], r["note_id"]))
            self.count("corrections")


def dataset_today(data_dir):
    """'Today' from the README next to the dataset ("Today" is 15 Jan 2027), else None."""
    for readme in (data_dir / "README.md", data_dir.parent / "README.md"):
        if readme.exists():
            m = TODAY_RE.search(readme.read_text())
            if m:
                return parse_date(" ".join(m.groups()))
    return None


def check(conn, warnings):
    for table, rowid, parent, fkid in conn.execute("PRAGMA foreign_key_check"):
        warnings.append(f"foreign key: {table} rowid {rowid} -> {parent} missing")
    for (mid,) in conn.execute(
            "SELECT m.maintenance_id FROM maintenance m JOIN inspections i"
            " ON i.inspection_id = m.triggered_by_inspection_id AND i.spill_detected = 1"
            " JOIN maintenance_reports r ON r.maintenance_id = m.maintenance_id"
            " WHERE r.containment_hours IS NULL"):
        warnings.append(f"{mid}: spill repair report has no parsable containment time")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--data", type=Path, action="append",
                    help="dataset folder with fleet/ and assets/ (repeatable; default: the test data)")
    ap.add_argument("--sample", action="store_true", help="load the sample data instead")
    ap.add_argument("--today", help="set 'today' (YYYY-MM-DD); default: from the dataset README")
    args = ap.parse_args()
    data_dirs = args.data or [SAMPLE_DATA if args.sample else DEFAULT_DATA]

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA.read_text())
    # Wells are deleted and re-inserted inside one transaction; check FKs once at the end.
    conn.execute("PRAGMA foreign_keys = OFF")

    for data_dir in data_dirs:
        data_dir = data_dir.resolve()
        if not (data_dir / "fleet").is_dir() or not (data_dir / "assets").is_dir():
            sys.exit(f"{data_dir}: expected fleet/ and assets/ folders")
        loader = Loader(conn, data_dir)
        with conn:
            loader.load_fleet()
            loader.load_guide_rules()
            loader.load_wells()
            check(conn, loader.warnings)
            today = args.today or dataset_today(data_dir) or (SAMPLE_TODAY if data_dir == SAMPLE_DATA.resolve() else None)
            if today:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('today', ?)", (today,))
            conn.execute("INSERT INTO load_runs (loaded_at, data_dir, counts, warnings) VALUES (?,?,?,?)",
                         (now_iso(), str(data_dir), json.dumps(loader.counts), json.dumps(loader.warnings)))
        print(f"Loaded {data_dir}")
        for table, n in loader.counts.items():
            print(f"  {table:22s} {n:>7,}")
        for w in loader.warnings:
            print(f"  WARNING: {w}")

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO search_fts(search_fts) VALUES ('optimize')")
    conn.commit()
    today = conn.execute("SELECT value FROM settings WHERE key = 'today'").fetchone()[0]
    conn.close()
    print(f"Database: {args.db} (today = {today})")


if __name__ == "__main__":
    main()
