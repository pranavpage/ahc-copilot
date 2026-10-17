"""Load one or more dataset folders into the copilot's SQLite database.

    python db/load.py                                  # sample data -> data/copilot.db
    python db/load.py --data path/to/test-data         # load the test dataset alongside
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
DEFAULT_DATA = ROOT / "flytbase-ahc-swe-asset-intelligence-dataset" / "sample-data"
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
        ]:
            c.execute(sql, (asset_id,))

    def load_well(self, wdir):
        c = self.c
        meta = json.loads((wdir / "metadata.json").read_text())
        wid = meta["asset_id"]
        self.clear_well(wid)

        loc, last = meta.get("location") or {}, meta.get("last_inspection") or {}
        c.execute("INSERT OR REPLACE INTO wells VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            wid, meta["name"], meta.get("asset_category"), meta["well_type"], meta.get("area_id"),
            meta.get("team_id"), meta.get("in_charge_user_id"), loc.get("lat"), loc.get("lon"),
            meta.get("installed_on"), meta.get("recorded_status"), last.get("inspection_id"),
            last.get("inspected_at"), last.get("inspector_user_id")))
        self.count("wells")
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
                " evidence_images, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["inspection_id"], wid, r["inspected_at"], r.get("inspector_user_id"), r.get("method"),
                 r.get("ambient_temp_c"), r.get("wellhead_temp_c"), int(bool(r.get("spill_detected"))),
                 r.get("spill_area_pct"), r.get("spill_est_volume_bbl"),
                 json.dumps(r.get("evidence_images") or []), r.get("notes") or ""))
            if r.get("notes"):
                c.execute("INSERT INTO search_fts VALUES ('inspection_note', ?, ?, ?, ?)",
                          (r["inspection_id"], wid, f"Inspection {r['inspection_id']} {r['inspected_at'][:10]}", r["notes"]))
            self.count("inspections")

        for r in read_jsonl(wdir / "maintenance.jsonl"):
            cost = r.get("cost_usd") or {}
            c.execute("INSERT INTO maintenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                r["maintenance_id"], wid, r["started_at"], r.get("completed_at"), r["maintenance_type"],
                r.get("equipment_kind"), r.get("issue"), r.get("action_taken"), r.get("technician_user_id"),
                r.get("contractor"), r.get("downtime_hours"), cost.get("labor"), cost.get("parts"),
                cost.get("total"), r.get("triggered_by_inspection_id"), r.get("report_file")))
            self.count("maintenance")
            if r.get("report_file"):
                self.load_report(wdir, wid, r["maintenance_id"], r["report_file"])

        for r in read_jsonl(wdir / "regulatory-events.jsonl"):
            c.execute("INSERT INTO regulatory_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                r["event_id"], wid, r["date"], r.get("agency"), r["event_type"], r.get("protocol_id"),
                r.get("related_inspection_id"), r.get("detail"), r.get("hours_to_report"),
                r.get("fine_usd"), r.get("status")))
            self.count("regulatory_events")

        for r in read_jsonl(wdir / "context.jsonl"):
            self.load_note(wid, r)

    def load_report(self, wdir, wid, mid, report_file):
        path = wdir / report_file
        if not path.exists():
            self.warn(f"{mid}: report_file {report_file} not found")
            return
        md = path.read_text()
        sections = split_sections(md, 2)
        title = next((h for lvl, h, _ in sections if lvl == 1), mid)
        m = CONTAINMENT_RE.search(md.replace("**", ""))
        self.c.execute("INSERT INTO maintenance_reports VALUES (?,?,?,?,?,?)",
                       (mid, wid, self.rel(path), title, md, float(m.group(1)) if m else None))
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
        self.c.execute(
            "INSERT INTO notes (note_id, source, asset_id, created_at, author_user_id, note_type,"
            " inspection_id, text, valid_from, valid_to) VALUES (?, 'dataset', ?,?,?,?,?,?,?,?)",
            (r["note_id"], wid, r["created_at"], r.get("author_user_id"), r["note_type"],
             r.get("inspection_id"), r["text"], r.get("valid_from"), r.get("valid_to")))
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
                    help="dataset folder with fleet/ and assets/ (repeatable)")
    args = ap.parse_args()
    data_dirs = args.data or [DEFAULT_DATA]

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
    conn.close()
    print(f"Database: {args.db}")


if __name__ == "__main__":
    main()
