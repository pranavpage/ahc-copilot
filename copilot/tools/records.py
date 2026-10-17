"""Spills, per-well records and document search. Owner: A2.

Backed by the `spills` view, the record tables and `search_fts` + `rules` (db/schema.sql).
Dates are YYYY-MM-DD. `area` is a name ("Northeast Block 8") or an ID ("NE-08").
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import Literal

from copilot import db, results
from copilot.tools.base import ToolResult, correction_details, correction_note, user_rule_cite

MAX_ROWS = 200

GroupField = Literal["area", "month", "asset_id", "spill_class"]

# Section order in well_records. Findings come first so the row cap never drops them.
SECTIONS = ["findings", "repairs", "events", "report_findings", "notes"]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _result(kind: str, rows: list[dict], ids: list[str], notes: list[str]) -> ToolResult:
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    if truncated:
        notes = notes + [f"truncated to the first {MAX_ROWS} rows; narrow the filter"]
    ids = list(dict.fromkeys(i for i in ids if i))
    return ToolResult(result_id=results.put(kind, rows), kind=kind, rows=rows, ids=ids,
                      notes=notes, truncated=truncated)


def _empty(kind: str, note: str) -> ToolResult:
    return _result(kind, [], [], [note])


def _date_note(**dates: str | None) -> str | None:
    """A note if any date is not YYYY-MM-DD, or if start is after end."""
    for name, value in dates.items():
        if value is None:
            continue
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            return f"bad {name} date '{value}'; use YYYY-MM-DD"
    start, end = dates.get("start"), dates.get("end")
    if start and end and start > end:
        return f"start {start} is after end {end}"
    return None


def _resolve_area(area: str) -> tuple[str | None, str | None]:
    """(area_id, None) or (None, note listing the valid names)."""
    found = db.rows("SELECT area_id FROM areas WHERE area_id = :a OR lower(name) = lower(:a)", {"a": area})
    if found:
        return found[0]["area_id"], None
    names = [r["name"] for r in db.rows("SELECT name FROM areas ORDER BY name")]
    return None, f"unknown area '{area}'; valid: {', '.join(names)}"


def _well_exists(asset_id: str) -> bool:
    return bool(db.rows("SELECT 1 FROM wells WHERE asset_id = ?", (asset_id,)))


def _cite(rule: dict) -> str:
    """Citation for a well_rules row: `<doc_id> §<section_path>`, or the user rule."""
    if rule.get("doc_id"):
        return f"{rule['doc_id']} §{rule['section_path']}"
    return user_rule_cite(rule["rule_id"], rule.get("author_user_id"))


def _well_rules(asset_id: str) -> dict[str, dict]:
    return {r["rule_key"]: r for r in db.rows("SELECT * FROM well_rules WHERE asset_id = ?", (asset_id,))}


def _protocol_cite(protocol_id: str) -> str | None:
    """Citation for a protocol that has no numeric rule (e.g. a yearly test): the SOP section that states it."""
    found = db.rows(
        "SELECT s.doc_id, s.section_path FROM doc_sections s JOIN documents d ON d.doc_id = s.doc_id"
        " WHERE s.body LIKE '%' || ? || '%' ORDER BY (d.kind = 'sop') DESC, s.doc_id, s.ord LIMIT 1",
        (protocol_id,))
    return f"{found[0]['doc_id']} §{found[0]['section_path']}" if found else None


def _num(x: float | None) -> float | int | None:
    """12.0 -> 12, for readable details."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


# ----------------------------------------------------------------------------
# spills
# ----------------------------------------------------------------------------

def spills(
    start: str | None = None,
    end: str | None = None,
    asset_id: str | None = None,
    area: str | None = None,
    group_by: list[GroupField] | None = None,
) -> ToolResult:
    """Real spills (after corrections) discovered between start and end (inclusive).

    Per spill: inspection ID, well, area, lat/lon, date, volume (bbl), class from the Spill
    Response SOP, reportable yes/no (with the spill report filed, or when it was due), the repair
    and report, containment hours vs. the limit, and who corrected the detection (`corrections`).
    Filter by well or area. Notes list detections that corrections cancelled and missing reports.
    `group_by` (any of "area", "month", "asset_id", "spill_class") returns one row per group
    with spill_count and total_bbl instead, e.g. ["area", "month"] for a heatmap.

    Owner: A2.
    """
    kind = "spills"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    area_id = None
    if area:
        area_id, note = _resolve_area(area)
        if note:
            return _empty(kind, note)
    if asset_id and not _well_exists(asset_id):
        return _empty(kind, f"unknown well '{asset_id}'")
    if group_by:
        bad = [g for g in group_by if g not in GroupField.__args__]
        if bad:
            return _empty(kind, f"unknown group_by {bad}; valid: {', '.join(GroupField.__args__)}")

    params = {"start": start, "end": end, "asset_id": asset_id, "area_id": area_id}
    where = """(:start IS NULL OR {t}.inspected_date >= :start)
           AND (:end IS NULL OR {t}.inspected_date <= :end)
           AND (:asset_id IS NULL OR {t}.asset_id = :asset_id)
           AND (:area_id IS NULL OR {t}.area_id = :area_id)"""

    found = db.rows(f"""
        SELECT s.asset_id, a.name AS area_name, w.lat, w.lon,
               s.inspection_id, s.inspected_date,
               s.spill_volume_bbl, s.raw_spill_est_volume_bbl,
               s.spill_class, s.is_reportable,
               s.maintenance_id, s.report_path, s.containment_hours,
               lim.value AS containment_limit_hours, lim.doc_id, lim.section_path, lim.rule_id,
               lim.author_user_id, s.correction_ids, s.inspected_at,
               (SELECT ev.event_id FROM regulatory_events ev WHERE ev.event_type = 'spill_report_filed'
                  AND ev.related_inspection_id = s.inspection_id ORDER BY ev.date LIMIT 1) AS report_event_id,
               (SELECT value FROM well_rules n WHERE n.asset_id = s.asset_id AND n.rule_key =
                  CASE WHEN s.spill_class = 'major' THEN 'spill_notice_hours_major' ELSE 'spill_notice_hours' END)
                  AS notice_hours
        FROM spills s
        JOIN wells w ON w.asset_id = s.asset_id
        LEFT JOIN areas a ON a.area_id = s.area_id
        LEFT JOIN well_rules lim ON lim.asset_id = s.asset_id AND lim.rule_key = 'containment_max_hours'
        WHERE {where.format(t='s')}
        ORDER BY s.inspected_at, s.asset_id""", params)

    ids: list[str] = []
    notes: list[str] = []
    rows: list[dict] = []
    for r in found:
        limit = r["containment_limit_hours"]
        if limit is not None:
            ids.append(_cite(r))
        row = {
            "asset_id": r["asset_id"], "area_name": r["area_name"], "lat": r["lat"], "lon": r["lon"],
            "inspection_id": r["inspection_id"], "inspected_date": r["inspected_date"],
            "spill_volume_bbl": r["spill_volume_bbl"],
        }
        if r["raw_spill_est_volume_bbl"] != r["spill_volume_bbl"]:
            row["raw_spill_est_volume_bbl"] = r["raw_spill_est_volume_bbl"]
        hours = r["containment_hours"]
        correction_ids = (r["correction_ids"] or "").split()
        row |= {
            "spill_class": r["spill_class"], "is_reportable": bool(r["is_reportable"]),
            "maintenance_id": r["maintenance_id"], "report_path": r["report_path"],
            "containment_hours": hours, "containment_limit_hours": limit,
            "contained_in_time": None if hours is None or limit is None else hours <= limit,
            "correction_ids": correction_ids,
        }
        if r["is_reportable"]:
            row["spill_report"] = r["report_event_id"]
            if not r["report_event_id"] and r["notice_hours"] is not None:
                due = datetime.fromisoformat(r["inspected_at"].replace("Z", "+00:00")) + timedelta(hours=r["notice_hours"])
                row["spill_report_due"] = due.date().isoformat()
                overdue = row["spill_report_due"] < db.today()
                notes.append(f"{r['inspection_id']} ({r['asset_id']}): reportable, no spill report filed; due "
                             f"{row['spill_report_due']} ({_num(r['notice_hours'])} h){', overdue' if overdue else ''}")
        if correction_ids:
            row["corrections"] = correction_details(correction_ids)
            notes += [correction_note(c) for c in row["corrections"]]
        rows.append(row)
        ids += [r["inspection_id"], r["maintenance_id"], r["report_event_id"], *correction_ids]
    if any(r["containment_limit_hours"] is None for r in found):
        notes.append("no rule found: containment_max_hours (for some wells)")

    spill_rules = db.rows(
        "SELECT DISTINCT doc_id, section_path, rule_id FROM well_rules WHERE rule_key IN"
        " ('spill_moderate_min_bbl', 'spill_reportable_min_bbl', 'spill_major_min_bbl')"
        " AND asset_id IN (SELECT value FROM json_each(:ids))",
        {"ids": _json_list({r["asset_id"] for r in found})})
    ids += [_cite(r) for r in spill_rules]

    cancelled = db.rows(f"""
        SELECT e.inspection_id, e.correction_ids FROM inspections_effective e
        WHERE e.raw_spill_detected = 1 AND e.spill_detected = 0 AND {where.format(t='e')}
        ORDER BY e.inspected_at""", params)
    if cancelled:
        cor = [c for r in cancelled for c in (r["correction_ids"] or "").split()]
        notes.append(
            f"{len(cancelled)} detection(s) cancelled by corrections and not counted: "
            + ", ".join(f"{r['inspection_id']} ({r['correction_ids']})" for r in cancelled))
        ids += [r["inspection_id"] for r in cancelled] + cor

    if group_by:
        rows = _group(rows, group_by)
    if not rows:
        notes.append("no spills match the filter")
    return _result(kind, rows, ids, notes)


def _json_list(values) -> str:
    return json.dumps(sorted(values))


def _group(rows: list[dict], group_by: list[str]) -> list[dict]:
    field = {"area": "area_name", "month": "inspected_date", "asset_id": "asset_id", "spill_class": "spill_class"}
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = tuple(r[field[g]][:7] if g == "month" else r[field[g]] for g in group_by)
        g = groups.setdefault(key, {**dict(zip(group_by, key)), "spill_count": 0, "total_bbl": 0.0})
        g["spill_count"] += 1
        g["total_bbl"] += r["spill_volume_bbl"] or 0
    out = [groups[k] for k in sorted(groups, key=lambda k: tuple(str(x) for x in k))]
    for g in out:
        g["total_bbl"] = round(g["total_bbl"], 2)
    return out


# ----------------------------------------------------------------------------
# well_records
# ----------------------------------------------------------------------------

def well_records(asset_id: str, start: str, end: str) -> ToolResult:
    """All records of one well between start and end (inclusive), to judge it against the rules.

    One result with a `section` per row:
    - findings: deterministic rule checks {rule, status breach|open|met, detail, ids, due_date}
      for SR-01 (spill report), SR-02 (containment), SR-03 (cleanup verification),
      RC-04 (NOV response), RCA (repeat corrective repairs, counted back from today)
      and RC-02 (yearly flowline integrity test).
    - repairs (with report and containment hours), events (plus every open event),
      report_findings (report compliance rows not "Met"), notes valid in the period.

    Owner: A2.
    """
    kind = "well_records"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    if not _well_exists(asset_id):
        return _empty(kind, f"unknown well '{asset_id}'")

    p = {"a": asset_id, "start": start, "end": end}
    today = db.today()
    rules = _well_rules(asset_id)
    ids: list[str] = []
    notes: list[str] = []

    repairs = db.rows("""
        SELECT m.maintenance_id, substr(m.started_at, 1, 10) AS date, m.started_at, m.completed_at,
               m.maintenance_type, m.equipment_kind, m.issue, m.action_taken, m.downtime_hours,
               m.cost_total_usd, m.triggered_by_inspection_id,
               mr.file_path AS report_path, mr.containment_hours
        FROM maintenance m LEFT JOIN maintenance_reports mr ON mr.maintenance_id = m.maintenance_id
        WHERE m.asset_id = :a AND substr(m.started_at, 1, 10) BETWEEN :start AND :end
        ORDER BY m.started_at, m.maintenance_id""", p)
    events = db.rows("""
        SELECT event_id, date, agency, event_type, protocol_id, related_inspection_id, detail,
               hours_to_report, fine_usd, status
        FROM regulatory_events
        WHERE asset_id = :a AND (date BETWEEN :start AND :end OR status = 'open')
        ORDER BY date, event_id""", p)
    well_notes = db.rows("""
        SELECT n.note_id, substr(n.created_at, 1, 10) AS date, n.source, n.created_at, n.author_user_id,
               u.name AS author_name, n.note_type, n.inspection_id, n.text, n.valid_from, n.valid_to,
               n.claim_status
        FROM notes n LEFT JOIN users u ON u.user_id = n.author_user_id
        WHERE asset_id = :a AND COALESCE(claim_status, '') <> 'retracted'
          AND (substr(created_at, 1, 10) BETWEEN :start AND :end
               OR (COALESCE(valid_from, substr(created_at, 1, 10)) <= :end
                   AND (valid_to IS NULL OR valid_to >= :start)))
        ORDER BY created_at, note_id""", p)
    report_findings = db.rows("""
        SELECT rc.maintenance_id, substr(m.started_at, 1, 10) AS date, rc.protocol, rc.result, rc.detail
        FROM report_compliance rc JOIN maintenance m ON m.maintenance_id = rc.maintenance_id
        WHERE m.asset_id = :a AND substr(m.started_at, 1, 10) BETWEEN :start AND :end
          AND rc.result <> 'Met'
        ORDER BY m.started_at, rc.maintenance_id, rc.protocol""", p)

    ids += [r["maintenance_id"] for r in repairs] + [r["event_id"] for r in events]
    ids += [r["note_id"] for r in well_notes]

    findings = _findings(asset_id, start, end, today, rules, notes)
    for f in findings:
        ids += f["ids"]
        if f.get("cite"):
            ids.append(f["cite"])

    rows = []
    for section, items in [("findings", findings), ("repairs", repairs), ("events", events),
                           ("report_findings", report_findings), ("notes", well_notes)]:
        rows += [{"section": section, **r} for r in items]
    rows.sort(key=lambda r: (SECTIONS.index(r["section"]), r.get("date") or ""))
    return _result(kind, rows, ids, notes)


def _findings(asset_id: str, start: str, end: str, today: str,
              rules: dict[str, dict], notes: list[str]) -> list[dict]:
    """Deterministic rule checks for one well. Every threshold comes from `rules`."""

    def rule(key: str) -> dict | None:
        if key not in rules:
            notes.append(f"no rule found: {key}")
        return rules.get(key)

    out: list[dict] = []
    events = db.rows("SELECT * FROM regulatory_events WHERE asset_id = ? ORDER BY date, event_id", (asset_id,))
    open_inspections = {e["related_inspection_id"] for e in events if e["status"] == "open"}
    spills_ = db.rows("""
        SELECT inspection_id, inspected_at, inspected_date, spill_volume_bbl, spill_class, is_reportable,
               maintenance_id, containment_hours
        FROM spills WHERE asset_id = :a
          AND (inspected_date BETWEEN :start AND :end
               OR inspection_id IN (SELECT value FROM json_each(:open)))
        ORDER BY inspected_at""", {"a": asset_id, "start": start, "end": end,
                                   "open": _json_list(i for i in open_inspections if i)})

    def related(spill: dict, event_type: str) -> list[dict]:
        return [e for e in events if e["event_type"] == event_type
                and e["related_inspection_id"] == spill["inspection_id"]]

    for s in spills_:
        sid, found_on = s["inspection_id"], s["inspected_date"]
        base_ids = [sid, s["maintenance_id"]] if s["maintenance_id"] else [sid]

        # SR-01: written spill report within the limit (shorter for a major spill).
        if s["is_reportable"]:
            key = "spill_notice_hours_major" if s["spill_class"] == "major" else "spill_notice_hours"
            r = rule(key)
            if r:
                limit = r["value"]
                reports = related(s, "spill_report_filed")
                f = {"rule": "SR-01", "date": found_on, "cite": _cite(r)}
                if not reports:
                    due = datetime.fromisoformat(s["inspected_at"].replace("Z", "+00:00")) + timedelta(hours=limit)
                    late = due.date().isoformat() < today
                    f |= {"status": "breach" if late else "open", "ids": base_ids,
                          "due_date": due.date().isoformat(),
                          "detail": f"{s['spill_class']} spill {sid} ({s['spill_volume_bbl']} bbl) has no "
                                    f"spill_report_filed event (limit {_num(limit)} h)"}
                else:
                    rep = reports[0]
                    hrs = rep["hours_to_report"]
                    over = hrs is not None and hrs > limit
                    f |= {"status": "breach" if over else "met", "ids": base_ids + [rep["event_id"]],
                          "detail": f"spill report {rep['event_id']} filed {_num(hrs)} h after discovery of "
                                    f"{sid} (limit {_num(limit)} h)"}
                out.append(f)

        # SR-02: contained within the limit.
        r = rule("containment_max_hours")
        if r:
            limit, hrs = r["value"], s["containment_hours"]
            f = {"rule": "SR-02", "date": found_on, "cite": _cite(r), "ids": base_ids}
            if hrs is None:
                f |= {"status": "open", "detail": f"no containment time recorded for spill {sid} "
                                                  f"(limit {_num(limit)} h)"}
            else:
                f |= {"status": "breach" if hrs > limit else "met",
                      "detail": f"spill {sid} contained after about {_num(hrs)} h (limit {_num(limit)} h)"}
            out.append(f)

        # SR-03: agency verification of the cleanup (closed site inspection) within the limit.
        if s["is_reportable"]:
            r = rule("cleanup_verification_days")
            if r:
                due = (date.fromisoformat(found_on) + timedelta(days=r["value"])).isoformat()
                visits = related(s, "site_inspection")
                closed = [e for e in visits if e["status"] == "closed"]
                f = {"rule": "SR-03", "date": found_on, "cite": _cite(r), "due_date": due,
                     "ids": base_ids + [e["event_id"] for e in visits]}
                if closed:
                    f |= {"status": "met", "detail": f"cleanup of {sid} verified by closed site inspection "
                                                     f"{closed[0]['event_id']} on {closed[0]['date']}"}
                else:
                    open_ = ", ".join(f"{e['event_id']} open" for e in visits) or "no site inspection"
                    f |= {"status": "breach" if today > due else "open",
                          "detail": f"cleanup of {sid} not verified by the agency ({open_}); "
                                    f"due {due} ({_num(r['value'])} days after discovery)"}
                out.append(f)

    # RC-04: answer each notice of violation within the limit.
    novs = [e for e in events if e["event_type"] == "notice_of_violation"
            and (start <= e["date"] <= end or e["status"] == "open")]
    if novs and (r := rule("nov_response_days")):
        for nov in novs:
            due = (date.fromisoformat(nov["date"]) + timedelta(days=r["value"])).isoformat()
            responses = [e for e in events if e["event_type"] == "nov_response_filed" and e["date"] >= nov["date"]
                         and (not nov["related_inspection_id"]
                              or e["related_inspection_id"] == nov["related_inspection_id"])]
            f = {"rule": "RC-04", "date": nov["date"], "cite": _cite(r), "due_date": due,
                 "ids": [nov["event_id"]] + [e["event_id"] for e in responses[:1]]}
            if responses:
                resp = responses[0]
                f |= {"status": "met" if resp["date"] <= due else "breach",
                      "detail": f"notice {nov['event_id']} answered by {resp['event_id']} on {resp['date']} "
                                f"(due {due}); notice status {nov['status']}"}
            else:
                f |= {"status": "breach" if today > due else "open",
                      "detail": f"notice {nov['event_id']} ({nov['date']}) has no nov_response_filed event; "
                                f"due {due}; notice status {nov['status']}"}
            out.append(f)

    # RCA: corrective repairs per equipment kind in the window before today.
    r_count, r_window = rule("rca_corrective_count"), rule("rca_window_months")
    if r_count and r_window:
        since = db.rows("SELECT date(?, ?) AS d", (today, f"-{_num(r_window['value'])} months"))[0]["d"]
        repairs = db.rows("""
            SELECT maintenance_id, equipment_kind, substr(started_at, 1, 10) AS d FROM maintenance
            WHERE asset_id = ? AND maintenance_type = 'corrective'
              AND substr(started_at, 1, 10) >= ? AND substr(started_at, 1, 10) <= ?
            ORDER BY started_at""", (asset_id, since, today))
        by_kind: dict[str, list[dict]] = {}
        for m in repairs:
            by_kind.setdefault(m["equipment_kind"] or "unknown", []).append(m)
        limit = r_count["value"]
        for kind_, ms in sorted(by_kind.items()):
            n = len(ms)
            out.append({
                "rule": "RCA", "status": "open" if n >= limit else "met", "date": ms[-1]["d"],
                "cite": _cite(r_count), "ids": [m["maintenance_id"] for m in ms],
                "detail": f"{n} corrective {kind_} repair(s) from {since} to {today} "
                          f"(RCA required at {_num(limit)}; {_cite(r_count)})",
            })

    # RC-02: a scheduled flowline integrity test in each calendar year of the window.
    has_flowline = db.rows("SELECT 1 FROM equipment WHERE asset_id = ? AND kind = 'flowline'", (asset_id,))
    if has_flowline:
        cite = _protocol_cite("RC-02")
        tests = db.rows("""
            SELECT maintenance_id, substr(started_at, 1, 10) AS d FROM maintenance
            WHERE asset_id = ? AND maintenance_type = 'scheduled' AND equipment_kind = 'flowline'
              AND lower(issue) LIKE '%integrity test%'
            ORDER BY started_at""", (asset_id,))
        for year in range(int(start[:4]), min(int(end[:4]), int(today[:4])) + 1):
            done = [t for t in tests if t["d"][:4] == str(year)]
            f = {"rule": "RC-02", "date": f"{year}-12-31", "cite": cite, "due_date": f"{year}-12-31",
                 "ids": [t["maintenance_id"] for t in done]}
            if done:
                f |= {"status": "met", "date": done[0]["d"],
                      "detail": f"flowline integrity test in {year}: {done[0]['maintenance_id']} on {done[0]['d']}"}
            else:
                f |= {"status": "open" if str(year) == today[:4] else "breach",
                      "detail": f"no flowline integrity test recorded in {year}"}
            out.append(f)

    return out


# ----------------------------------------------------------------------------
# search_docs
# ----------------------------------------------------------------------------

def search_docs(query: str, asset_id: str | None = None, limit: int = 5) -> ToolResult:
    """Full-text search over manuals, SOPs, maintenance reports and notes.

    Returns the best `limit` sections with their citation (document and section, or record ID).
    `asset_id` limits well-specific text to one well; manuals and SOPs are always searched.

    Owner: A2.
    """
    kind = "search_docs"
    words = re.findall(r"\w+", query or "")
    if not words:
        return _empty(kind, "empty query; give some words to search for")
    limit = max(1, min(int(limit or 5), 50))
    match = " OR ".join(f'"{w}"' for w in words)
    found = db.rows("""
        SELECT kind, ref_id, asset_id, heading,
               snippet(search_fts, 4, '**', '**', '…', 30) AS snippet
        FROM search_fts
        WHERE search_fts MATCH :q AND (:a IS NULL OR asset_id = :a OR asset_id IS NULL)
        ORDER BY bm25(search_fts)
        LIMIT :n""", {"q": match, "a": asset_id, "n": limit})

    paths = _doc_section_paths({r["ref_id"] for r in found if r["kind"] == "doc_section"})
    rows, ids = [], []
    for r in found:
        cite = r["ref_id"]
        if r["kind"] == "doc_section":
            path = next((p for p in paths.get(r["ref_id"], []) if r["heading"].endswith(f" — {p}")), None)
            cite = f"{r['ref_id']} §{path}" if path else r["ref_id"]
        rows.append({**r, "cite": cite})
        ids.append(cite)
    notes = [] if rows else [f"no matches for '{query}'"]
    return _result(kind, rows, ids, notes)


def _doc_section_paths(doc_ids: set[str]) -> dict[str, list[str]]:
    """Section paths per document, longest first (so the most specific suffix matches)."""
    out: dict[str, list[str]] = {}
    for r in db.rows("SELECT doc_id, section_path FROM doc_sections WHERE doc_id IN"
                     " (SELECT value FROM json_each(?))", (_json_list(doc_ids),)):
        out.setdefault(r["doc_id"], []).append(r["section_path"])
    for paths in out.values():
        paths.sort(key=len, reverse=True)
    return out
