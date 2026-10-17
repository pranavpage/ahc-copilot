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
Section = Literal["findings", "repairs", "events", "report_findings", "notes"]

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
    reportable_only: bool = False,
    not_contained_only: bool = False,
) -> ToolResult:
    """Real spills (after corrections) discovered between start and end (inclusive).

    Per spill: inspection ID, well, area, lat/lon, date, volume (bbl), class from the Spill
    Response SOP, reportable yes/no (with the spill report filed, or when it was due), the repair
    and report, containment hours vs. the limit, and who corrected the detection (`corrections`).
    Notes on the spill (e.g. people who disagree about it) are in `notes_on_spill`.
    Filter by well or area; `reportable_only` keeps spills that needed a report to the regulator,
    `not_contained_only` keeps spills not contained within the limit (so a table shows only those).
    Notes list detections that corrections cancelled (and why), and missing reports.
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
                             f"{row['spill_report_due']} ({_num(r['notice_hours'])} h){', overdue' if overdue else ''} (say so)")
        if correction_ids:
            row["corrections"] = correction_details(correction_ids)
            notes += [correction_note(c) for c in row["corrections"]]
        if reportable_only and not row["is_reportable"]:
            continue
        if not_contained_only and row["contained_in_time"] is not False:
            continue
        rows.append(row)
        ids += [r["inspection_id"], r["maintenance_id"], r["report_event_id"], *correction_ids]
    if any(r["containment_limit_hours"] is None for r in found):
        notes.append("no rule found: containment_max_hours (for some wells)")
    if reportable_only or not_contained_only:
        kept = {r["inspection_id"] for r in rows}
        ids = [i for i in ids if i and (not i.startswith("INS-") or i in kept)]
        notes.append(f"{len(rows)} of {len(found)} spills kept by the filter "
                     f"({'reportable' if reportable_only else ''}{' and ' if reportable_only and not_contained_only else ''}"
                     f"{'not contained in time' if not_contained_only else ''})")

    # Notes that name the spill's inspection: people who agree or disagree with the detection.
    for row in rows:
        linked = db.rows("""
            SELECT n.note_id, u.name AS author_name, substr(n.created_at, 1, 10) AS date, n.text
            FROM notes n LEFT JOIN users u ON u.user_id = n.author_user_id
            WHERE n.asset_id = :a AND n.note_type <> 'correction'
              AND (n.inspection_id = :i OR n.text LIKE '%' || :i || '%')
            ORDER BY n.created_at""", {"a": row["asset_id"], "i": row["inspection_id"]})
        if linked:
            row["notes_on_spill"] = linked
            ids += [n["note_id"] for n in linked]
            if len(rows) > 20:
                continue
            notes.append(f"{row['inspection_id']}: {len(linked)} note(s) on this spill: " + "; ".join(
                f"{n['note_id']} by {n['author_name']}: '{n['text']}'" for n in linked)
                + ". None is a formal correction, so the detection stands; show both sides (say so)")

    spill_rules = db.rows(
        "SELECT DISTINCT doc_id, section_path, rule_id FROM well_rules WHERE rule_key IN"
        " ('spill_moderate_min_bbl', 'spill_reportable_min_bbl', 'spill_major_min_bbl')"
        " AND asset_id IN (SELECT value FROM json_each(:ids))",
        {"ids": _json_list({r["asset_id"] for r in found})})
    ids += [_cite(r) for r in spill_rules]

    cancelled = db.rows(f"""
        SELECT e.inspection_id, e.inspected_date, e.correction_ids FROM inspections_effective e
        WHERE e.raw_spill_detected = 1 AND e.spill_detected = 0 AND {where.format(t='e')}
        ORDER BY e.inspected_at""", params)
    if cancelled:
        cor = [c for r in cancelled for c in (r["correction_ids"] or "").split()]
        why = {c["correction_id"]: c for c in correction_details(cor)}
        if len(cancelled) > 5:      # a field-wide query: IDs only, to keep the result small
            why = {}
        notes.append(
            f"{len(cancelled)} detection(s) cancelled by corrections and not counted{' (say so)' if why else ''}: "
            + "; ".join(
                f"{r['inspection_id']} ({r['inspected_date']}): " + ", ".join(
                    f"{c} by {why[c]['corrected_by']}" + (f", note {why[c]['note_id']}" if why[c].get("note_id") else "")
                    + f": '{why[c]['reason']}'" for c in (r["correction_ids"] or "").split() if c in why)
                if why else f"{r['inspection_id']} ({r['correction_ids']})"
                for r in cancelled))
        ids += [r["inspection_id"] for r in cancelled] + cor + [c["note_id"] for c in why.values() if c.get("note_id")]

    if group_by:
        rows = _group(rows, group_by)
        if len(group_by) == 2:
            totals: dict = {}
            for g in rows:
                totals[g[group_by[0]]] = totals.get(g[group_by[0]], 0) + g["spill_count"]
            notes.append(f"spill_count totals per {group_by[0]} (state them): " + ", ".join(
                f"{k} {v}" for k, v in sorted(totals.items(), key=lambda kv: -kv[1])))
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

def well_records(asset_id: str, start: str, end: str, sections: list[Section] | None = None) -> ToolResult:
    """All records of one well between start and end (inclusive), to judge it against the rules.

    One result with a `section` per row:
    - findings: deterministic rule checks {rule, status breach|open|met, detail, ids, due_date}
      for SR-01 (spill report), SR-02 (containment), SR-03 (cleanup verification),
      RC-04 (NOV response), RCA (repeat corrective repairs, counted back from today)
      and RC-02 (yearly flowline integrity test).
    - repairs (with report, containment hours and cost; notes give the cost total), events (plus
      every open event), report_findings (report compliance rows not "Met"), notes valid in the
      period or written in it.
    `sections` keeps only those sections, e.g. ["findings"] for a table of the rule checks.
    Report each finding with its status as given: breach, open (still to do) or met.

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

    if repairs:
        total = sum(r["cost_total_usd"] or 0 for r in repairs)
        notes.append(f"{len(repairs)} repair(s) from {start} to {end}, cost total USD {_num(round(total, 2))}")
    rows = []
    for section, items in [("findings", findings), ("repairs", repairs), ("events", events),
                           ("report_findings", report_findings), ("notes", well_notes)]:
        if sections and section not in sections:
            continue
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
                                    f"{s['spill_class']} spill {sid} ({s['spill_volume_bbl']} bbl) "
                                    f"(limit {_num(limit)} h)"}
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
            fine = (f"; fine USD {_num(nov['fine_usd'])} ({nov['status']})" if nov["fine_usd"] else "")
            f = {"rule": "RC-04", "date": nov["date"], "cite": _cite(r), "due_date": due,
                 "ids": [nov["event_id"]] + [e["event_id"] for e in responses[:1]]}
            if responses:
                resp = responses[0]
                f |= {"status": "met" if resp["date"] <= due else "breach",
                      "detail": f"notice {nov['event_id']} answered by {resp['event_id']} on {resp['date']} "
                                f"(due {due}); notice status {nov['status']}{fine}"}
            else:
                f |= {"status": "breach" if today > due else "open",
                      "detail": f"notice {nov['event_id']} ({nov['date']}) has no nov_response_filed event; "
                                f"due {due}; notice status {nov['status']}{fine}"}
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
# repair_costs, rca_due
# ----------------------------------------------------------------------------

def repair_costs(asset_ids: list[str], start: str, end: str) -> ToolResult:
    """What repairs cost per well, between start and end (inclusive, by the repair's start date).

    Per well: number of repairs, total, labor and parts cost (USD), corrective and scheduled cost,
    downtime hours and the repair IDs. Use it for "what have repairs cost"; take the totals from
    here and never add costs up yourself. Wells with no repairs get a row with 0.
    """
    kind = "repair_costs"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    unknown = [a for a in asset_ids if not _well_exists(a)]
    notes = [f"unknown well(s): {', '.join(unknown)}"] if unknown else []
    found = db.rows("""
        SELECT asset_id, maintenance_id, maintenance_type, cost_total_usd, cost_labor_usd, cost_parts_usd,
               downtime_hours
        FROM maintenance
        WHERE asset_id IN (SELECT value FROM json_each(:ids)) AND substr(started_at, 1, 10) BETWEEN :start AND :end
        ORDER BY asset_id, started_at, maintenance_id""",
        {"ids": json.dumps(asset_ids), "start": start, "end": end})
    rows, ids = [], []
    for a in asset_ids:
        if a in unknown:
            continue
        ms = [m for m in found if m["asset_id"] == a]
        cost = lambda key, ms=ms: _num(round(sum(m[key] or 0 for m in ms), 2))  # noqa: E731
        rows.append({
            "asset_id": a, "repairs": len(ms), "cost_total_usd": cost("cost_total_usd"),
            "cost_labor_usd": cost("cost_labor_usd"), "cost_parts_usd": cost("cost_parts_usd"),
            "corrective_cost_usd": _num(round(sum(m["cost_total_usd"] or 0 for m in ms
                                                  if m["maintenance_type"] == "corrective"), 2)),
            "scheduled_cost_usd": _num(round(sum(m["cost_total_usd"] or 0 for m in ms
                                                 if m["maintenance_type"] == "scheduled"), 2)),
            "downtime_hours": sum(m["downtime_hours"] or 0 for m in ms),
            "maintenance_ids": [m["maintenance_id"] for m in ms],
        })
        ids += [m["maintenance_id"] for m in ms]
    if len(rows) > 1:
        notes.append(f"all {len(rows)} wells together: USD {_num(round(sum(r['cost_total_usd'] for r in rows), 2))}")
    return _result(kind, rows, ids, notes)


def rca_due(area: str | None = None, asset_ids: list[str] | None = None,
            equipment_kind: str | None = None) -> ToolResult:
    """Wells that need a root-cause analysis (RCA): repeated corrective repairs on the same equipment.

    Counts each well's corrective repairs per equipment kind in its rule window before today
    (`rca_window_months`) against its limit (`rca_corrective_count`): the manual for its well type,
    or a user rule, which wins within its scope. Rows: only the wells and equipment at or over the
    limit, with the count, the limit, the rule citation and the repair IDs. Filter by area or wells,
    and by `equipment_kind` (pump_jack, flowline, wellhead, downhole_pump, rod_string, separator).
    """
    kind = "rca_due"
    where, params = ["1"], {"today": db.today()}
    if area:
        area_id, note = _resolve_area(area)
        if note:
            return _empty(kind, note)
        where.append("w.area_id = :area_id")
        params["area_id"] = area_id
    if asset_ids:
        where.append("w.asset_id IN (SELECT value FROM json_each(:ids))")
        params["ids"] = json.dumps(asset_ids)
    if equipment_kind:
        where.append("m.equipment_kind = :eq")
        params["eq"] = equipment_kind
    found = db.rows(f"""
        SELECT w.asset_id, w.well_type, a.name AS area_name, m.equipment_kind,
               c.value AS rca_limit, c.rule_id, c.source, c.doc_id, c.section_path, c.author_user_id,
               win.value AS window_months, date(:today, '-' || CAST(win.value AS INTEGER) || ' months') AS since,
               COUNT(*) AS corrective_repairs, json_group_array(m.maintenance_id) AS ids,
               MAX(substr(m.started_at, 1, 10)) AS last_repair
        FROM wells w
        JOIN areas a ON a.area_id = w.area_id
        JOIN well_rules c ON c.asset_id = w.asset_id AND c.rule_key = 'rca_corrective_count'
        JOIN well_rules win ON win.asset_id = w.asset_id AND win.rule_key = 'rca_window_months'
        JOIN maintenance m ON m.asset_id = w.asset_id AND m.maintenance_type = 'corrective'
         AND substr(m.started_at, 1, 10) BETWEEN date(:today, '-' || CAST(win.value AS INTEGER) || ' months')
                                             AND :today
        WHERE {" AND ".join(where)}
        GROUP BY w.asset_id, m.equipment_kind
        ORDER BY w.asset_id, m.equipment_kind""", params)
    rows, ids, by_user = [], [], []
    for r in found:
        if r["corrective_repairs"] < r["rca_limit"]:
            continue
        cite = _cite(r)
        rows.append({
            "asset_id": r["asset_id"], "well_type": r["well_type"], "area_name": r["area_name"],
            "equipment_kind": r["equipment_kind"], "corrective_repairs": r["corrective_repairs"],
            "rca_limit": _num(r["rca_limit"]), "window": f"{r['since']} to {params['today']}",
            "rule": cite, "rule_source": r["source"], "last_repair": r["last_repair"],
            "maintenance_ids": sorted(json.loads(r["ids"])),
        })
        ids += rows[-1]["maintenance_ids"] + [cite]
        manual = db.rows("SELECT value, doc_id, section_path FROM rules WHERE rule_key = 'rca_corrective_count' "
                         "AND source = 'document' AND status = 'active' AND (well_type = ? OR well_type IS NULL) "
                         "ORDER BY well_type IS NULL LIMIT 1", (r["well_type"],))
        if r["source"] == "user" and manual and r["corrective_repairs"] < manual[0]["value"]:
            by_user.append(f"{r['asset_id']} ({r['well_type']}, {r['corrective_repairs']} repairs, {cite}; "
                           f"the manual {manual[0]['doc_id']} says {_num(manual[0]['value'])})")
    applied = db.rows(f"""
        SELECT w.well_type, c.value, c.rule_id, c.source, c.doc_id, c.section_path, c.author_user_id,
               COUNT(*) AS wells
        FROM wells w JOIN well_rules c ON c.asset_id = w.asset_id AND c.rule_key = 'rca_corrective_count'
        WHERE {" AND ".join(x for x in where if not x.startswith("m."))}
        GROUP BY w.well_type, c.rule_id ORDER BY w.well_type""", params)
    notes = ["limits applied: " + "; ".join(
        f"{a['well_type']}: {_num(a['value'])} corrective repairs ({_cite(a)}, {a['wells']} wells)" for a in applied)]
    if by_user:
        notes.append("added only because of a user rule, not the manual (say so): " + ", ".join(by_user))
    if not rows:
        notes.append("no well is at or over its RCA limit")
    return _result(kind, rows, ids, notes)


# ----------------------------------------------------------------------------
# search_docs
# ----------------------------------------------------------------------------

def search_docs(query: str, asset_id: str | None = None, limit: int = 5) -> ToolResult:
    """Full-text search over manuals, SOPs, maintenance reports and notes.

    Returns the best `limit` manual and SOP sections and, separately, the best `limit` record
    sections (maintenance reports, inspection and human notes), so the manuals are never crowded
    out by the many reports. Each row has its citation (document and section, or record ID).
    `asset_id` limits well-specific text to one well; manuals and SOPs are always searched.
    For "what kinds of X" or "every X", use `find_mentions`: it scans everything.

    Owner: A2.
    """
    kind = "search_docs"
    words = re.findall(r"\w+", query or "")
    if not words:
        return _empty(kind, "empty query; give some words to search for")
    limit = max(1, min(int(limit or 5), 50))
    match = " OR ".join(f'"{w}"' for w in words)
    found = []
    for docs in (True, False):
        found += db.rows(f"""
            SELECT kind, ref_id, asset_id, heading,
                   snippet(search_fts, 4, '**', '**', '…', 30) AS snippet
            FROM search_fts
            WHERE search_fts MATCH :q AND kind {'=' if docs else '<>'} 'doc_section'
              AND (:a IS NULL OR asset_id = :a OR asset_id IS NULL)
            ORDER BY bm25(search_fts)
            LIMIT :n""", {"q": match, "a": asset_id, "n": limit})

    rows, ids = [], []
    for r in found:
        cite = _fts_cite(r)
        rows.append({**r, "cite": cite})
        ids.append(cite)
    notes = [] if rows else [f"no matches for '{query}'"]
    return _result(kind, rows, ids, notes)


def _fts_cite(r: dict, paths: dict[str, list[str]] | None = None) -> str:
    """Citation of a search_fts row: '<doc_id> §<section>' for a manual section, else the record ID."""
    if r["kind"] != "doc_section":
        return r["ref_id"]
    paths = paths if paths is not None else _doc_section_paths({r["ref_id"]})
    path = next((p for p in paths.get(r["ref_id"], []) if r["heading"].endswith(f" — {p}")), None)
    return f"{r['ref_id']} §{path}" if path else r["ref_id"]


# ----------------------------------------------------------------------------
# find_mentions: every mention of a word, in all the data
# ----------------------------------------------------------------------------

STOP = set("""a an the and or but then than to of in on at by for from with without into onto over under
after before during while when where which who whom whose that this these those it its is are was were be
been being has have had do does did not no nor so as if each every all any some per via our their his her
we they he she you i me us them my your one two three four five six seven eight nine ten
also only just very more most less least such same other another""".split())
CLAUSE = re.compile(r"[;:|\n()\[\]!?,]|\.(?!\d)")     # a decimal point does not end a clause
WORD = re.compile(r"[A-Za-z][A-Za-z\-]*")
SOURCE_NAMES = {"doc_section": "manual/SOP sections", "report_section": "maintenance report sections",
                "inspection_note": "inspection notes", "note": "human notes",
                "maintenance_record": "maintenance records", "regulatory_event": "regulatory events"}
MAX_GROUPS = 40


def _group_key(text: str, start: int, end: int, lemma: str) -> str:
    """'pressure test', 'gas test', 'test dump valve': the content word before the term in the
    same clause; for a verb with no word before it ("…and tested the dump valve"), the words after."""
    before = CLAUSE.split(text[max(0, start - 80):start])[-1]
    prev = [w.lower() for w in WORD.findall(before)]
    content = [w for w in prev if w not in STOP]
    word = text[start:end].lower()
    verb = word.endswith(("ed", "ing")) and (not prev or prev[-1] in STOP)
    if content and not verb:
        return f"{content[-1].strip('-')} {lemma}"
    after = CLAUSE.split(text[end:end + 80])[0]
    nxt = [w.lower() for w in WORD.findall(after) if w.lower() not in STOP][:3]
    return f"{lemma} {' '.join(nxt)}".strip()


def find_mentions(terms: list[str], asset_id: str | None = None) -> ToolResult:
    """Find EVERY mention of a word in all the data, grouped by what each mention is about.

    Use it for "what kinds / types of X", "which records mention X", or to check that a list is
    complete. It scans all manual and SOP sections, maintenance reports, inspection notes, human
    notes, maintenance records and regulatory events, with no top-N limit. `terms`: the word and its
    synonyms, matched as word starts ("test" matches tests, tested, testing). One row per group: the
    words next to the term (e.g. "pressure test", "gas test"), how many mentions and records, the
    manual and SOP sections that state it, and example records with their text. Notes give how much
    data was scanned and the totals. Name every group in the answer (or say why one is left out)
    and give the totals.
    """
    kind = "find_mentions"
    terms = [t.strip().lower() for t in terms or [] if t and t.strip()]
    if not terms:
        return _empty(kind, "give at least one term, e.g. ['test']")
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\w*", re.I)
    lemma = terms[0]
    a = {"a": asset_id}

    scanned = {r["kind"]: r["n"] for r in db.rows(
        "SELECT kind, COUNT(*) AS n FROM search_fts WHERE (:a IS NULL OR asset_id = :a OR asset_id IS NULL) "
        "GROUP BY kind", a)}
    texts = db.rows(
        "SELECT kind, ref_id, asset_id, heading, body FROM search_fts WHERE search_fts MATCH :q "
        "AND (:a IS NULL OR asset_id = :a OR asset_id IS NULL)",
        {"q": " OR ".join(f'"{t}"*' for t in terms), **a})
    like = " OR ".join(f"{{col}} LIKE '%{t}%'" for t in terms)
    scanned["maintenance_record"] = db.rows(
        "SELECT COUNT(*) AS n FROM maintenance WHERE (:a IS NULL OR asset_id = :a)", a)[0]["n"]
    texts += [{"kind": "maintenance_record", "ref_id": m["maintenance_id"], "asset_id": m["asset_id"],
               "heading": None, "body": f"{m['issue']}. {m['action_taken'] or ''}"}
              for m in db.rows(f"""SELECT maintenance_id, asset_id, issue, action_taken FROM maintenance
                                   WHERE (:a IS NULL OR asset_id = :a)
                                     AND ({like.format(col='issue')} OR {like.format(col='action_taken')})""", a)]
    scanned["regulatory_event"] = db.rows(
        "SELECT COUNT(*) AS n FROM regulatory_events WHERE (:a IS NULL OR asset_id = :a)", a)[0]["n"]
    texts += [{"kind": "regulatory_event", "ref_id": e["event_id"], "asset_id": e["asset_id"],
               "heading": None, "body": e["detail"] or ""}
              for e in db.rows(f"""SELECT event_id, asset_id, detail FROM regulatory_events
                                   WHERE (:a IS NULL OR asset_id = :a) AND ({like.format(col='detail')})""", a)]

    paths = _doc_section_paths({t["ref_id"] for t in texts if t["kind"] == "doc_section"})
    groups: dict[str, dict] = {}
    total = 0
    for t in texts:
        for m in pattern.finditer(t["body"]):
            total += 1
            key = _group_key(t["body"], m.start(), m.end(), lemma)
            g = groups.setdefault(key, {"group": key, "mentions": 0, "records": set(), "sources": {},
                                        "doc_sections": [], "examples": []})
            g["mentions"] += 1
            ref = _fts_cite(t, paths) if t["kind"] == "doc_section" else t["ref_id"]
            if ref not in g["records"]:
                g["records"].add(ref)
                g["sources"][t["kind"]] = g["sources"].get(t["kind"], 0) + 1
                if t["kind"] == "doc_section":
                    g["doc_sections"].append(ref)
                elif len(g["examples"]) < 2:
                    g["examples"].append({"ref_id": ref, "text": "…" + t["body"][max(0, m.start() - 90):m.end() + 70]
                                          .replace("\n", " ").strip() + "…"})
    if not total:
        notes = [f"no mention of {', '.join(terms)} in any source (scanned: "
                 + ", ".join(f"{n} {SOURCE_NAMES.get(k, k)}" for k, n in scanned.items()) + ")"]
        return _result(kind, [], [], notes)

    ordered = sorted(groups.values(), key=lambda g: (-g["mentions"], g["group"]))
    # Small groups that no manual states (a few mentions, usually the word used in general) go
    # into one "other" row. A group that a manual or SOP states always gets its own row.
    small = max(3, total // 1000)
    main = [g for g in ordered if g["mentions"] >= small or g["doc_sections"]][:MAX_GROUPS]
    rest = [g for g in ordered if g not in main]
    rows = [{"group": g["group"], "mentions": g["mentions"], "records": len(g["records"]),
             "sources": g["sources"], "doc_sections": g["doc_sections"], "examples": g["examples"]}
            for g in main]
    if rest:
        rows.append({"group": "other", "mentions": sum(g["mentions"] for g in rest),
                     "records": len(set().union(*(g["records"] for g in rest))), "sources": {},
                     "doc_sections": sorted({d for g in rest for d in g["doc_sections"]}),
                     "examples": [{"ref_id": next(iter(sorted(g["records"]))), "text": g["group"]} for g in rest[:15]]})
    ids = [d for r in rows for d in r["doc_sections"]] + [e["ref_id"] for r in rows for e in r["examples"]]
    records = len({ref for g in groups.values() for ref in g["records"]})
    notes = [
        "scanned all data: " + ", ".join(f"{n} {SOURCE_NAMES.get(k, k)}" for k, n in scanned.items()),
        f"{total} mentions of {', '.join(terms)} in {records} records, in {len(rows)} groups; every mention "
        f"is in one group" + (f" ({rows[-1]['mentions']} in 'other': the word used in general or rare uses)"
                              if rest else "")
        + ". Name every group in the answer or say why it is left out, and give these totals (say so)",
    ]
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
