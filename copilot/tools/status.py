"""Well status, inspection history and downtime. Owner: A1.

Backed by the views `well_status_now` and `inspections_effective` (db/schema.sql).
Dates are YYYY-MM-DD. `area` is a name ("Northeast Block 8") or an ID ("NE-08").
"""

import json
from datetime import date

from copilot import db, results
from copilot.tools.base import ToolResult

MAX_ROWS = 200

PRODUCING_RULE = "production_min_delta_c"
DOWNTIME_RULE = "downtime_days_per_inspection"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(kind: str, rows: list[dict], ids: list[str], notes: list[str], truncated: bool = False) -> ToolResult:
    """Store the rows and build the ToolResult. IDs are de-duplicated, order kept."""
    return ToolResult(
        result_id=results.put(kind, rows),
        kind=kind,
        rows=rows,
        ids=list(dict.fromkeys(i for i in ids if i)),
        notes=notes,
        truncated=truncated,
    )


def _cap(rows: list[dict]) -> tuple[list[dict], bool]:
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


def _resolve_area(area: str) -> tuple[str | None, str | None]:
    """Area name or ID -> (area_id, None), or (None, note) if no area matches."""
    found = db.rows(
        "SELECT area_id FROM areas WHERE area_id = :a OR lower(name) = lower(:a)", {"a": area}
    )
    if found:
        return found[0]["area_id"], None
    names = [r["name"] for r in db.rows("SELECT name FROM areas ORDER BY name")]
    return None, f"unknown area '{area}'; valid: {', '.join(names)}"


def _known_wells(asset_ids: list[str]) -> set[str]:
    found = db.rows(
        "SELECT asset_id FROM wells WHERE asset_id IN (SELECT value FROM json_each(:ids))",
        {"ids": json.dumps(asset_ids)},
    )
    return {r["asset_id"] for r in found}


def _bad_dates(*values: str) -> str | None:
    """Note for the first value that is not a YYYY-MM-DD date, else None."""
    for v in values:
        try:
            date.fromisoformat(v)
        except (TypeError, ValueError):
            return f"invalid date '{v}'; use YYYY-MM-DD"
    return None


def _correction_ids(value: str | None) -> list[str]:
    return value.split() if value else []


def _rule_citations(asset_ids: list[str], rule_keys: list[str]) -> list[str]:
    """'<doc_id> § <section_path>' for the rules that apply to these wells."""
    found = db.rows(
        """
        SELECT DISTINCT doc_id, section_path FROM well_rules
        WHERE asset_id IN (SELECT value FROM json_each(:ids))
          AND rule_key IN (SELECT value FROM json_each(:keys))
          AND doc_id IS NOT NULL
        ORDER BY doc_id, section_path
        """,
        {"ids": json.dumps(asset_ids), "keys": json.dumps(rule_keys)},
    )
    return [f"{r['doc_id']} § {r['section_path']}" if r["section_path"] else r["doc_id"] for r in found]


def _num(value: float) -> str:
    """7.0 -> '7', 2.5 -> '2.5'."""
    return f"{value:g}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def well_status(
    asset_ids: list[str] | None = None,
    area: str | None = None,
    not_producing_only: bool = False,
) -> ToolResult:
    """Current status of wells, from each well's latest inspection.

    Per well: producing yes/no, °C above air vs. the threshold, the last inspection (ID, date,
    inspector, method), the recorded status and whether it is out of date, open repairs and
    valid notes that explain a stop. Filter by wells, by area, or to wells not producing.
    """
    kind = "well_status"
    notes: list[str] = []
    where, params = [], {}

    if area:
        area_id, note = _resolve_area(area)
        if note:
            return _result(kind, [], [], [note])
        where.append("s.area_id = :area_id")
        params["area_id"] = area_id
    if asset_ids:
        unknown = sorted(set(asset_ids) - _known_wells(asset_ids))
        if unknown:
            notes.append(f"unknown well(s): {', '.join(unknown)}")
        where.append("s.asset_id IN (SELECT value FROM json_each(:asset_ids))")
        params["asset_ids"] = json.dumps(asset_ids)
    if not_producing_only:
        where.append("NOT s.is_producing")

    found = db.rows(
        f"""
        SELECT s.asset_id, s.well_type, s.area_name, s.is_producing, s.temp_delta_c,
               s.producing_threshold_c, s.inspection_id, s.inspected_at, u.name AS inspector_name,
               s.method, s.inspection_notes, s.recorded_status, s.recorded_status_stale,
               s.correction_ids
        FROM well_status_now s
        LEFT JOIN users u ON u.user_id = s.inspector_user_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY s.asset_id
        LIMIT {MAX_ROWS + 1}
        """,
        params,
    )
    found, truncated = _cap(found)
    wells = [r["asset_id"] for r in found]
    today = db.today()
    p = {"ids": json.dumps(wells), "today": today}

    repairs: dict[str, list[dict]] = {}
    for m in db.rows(
        """
        SELECT asset_id, maintenance_id, issue, started_at, completed_at FROM maintenance
        WHERE asset_id IN (SELECT value FROM json_each(:ids))
          AND substr(started_at, 1, 10) <= :today
          AND (completed_at IS NULL OR :today < completed_at)
        ORDER BY asset_id, started_at
        """,
        p,
    ):
        repairs.setdefault(m.pop("asset_id"), []).append(m)

    current: dict[str, list[dict]] = {}
    for n in db.rows(
        """
        SELECT n.asset_id, n.note_id, u.name AS author_name, n.text, n.valid_from, n.valid_to
        FROM notes n
        LEFT JOIN users u ON u.user_id = n.author_user_id
        WHERE n.asset_id IN (SELECT value FROM json_each(:ids))
          AND n.note_type != 'correction'
          AND n.valid_from <= :today AND :today <= coalesce(n.valid_to, :today)
        ORDER BY n.asset_id, n.valid_from, n.note_id
        """,
        p,
    ):
        current.setdefault(n.pop("asset_id"), []).append(n)

    rows, ids = [], []
    for r in found:
        a = r["asset_id"]
        row = {
            **r,
            "is_producing": None if r["is_producing"] is None else bool(r["is_producing"]),
            "temp_delta_c": None if r["temp_delta_c"] is None else round(r["temp_delta_c"], 1),
            "recorded_status_stale": None
            if r["recorded_status_stale"] is None
            else bool(r["recorded_status_stale"]),
            "correction_ids": _correction_ids(r["correction_ids"]),
            "open_repairs": repairs.get(a, []),
            "current_notes": current.get(a, []),
        }
        if row["is_producing"] is None:
            notes.append(f"{a}: no producing rule found")
        elif not row["is_producing"] and not row["open_repairs"] and not row["current_notes"]:
            row["reason"] = None
            notes.append(f"{a}: no recorded reason")
        rows.append(row)
        ids += [row["inspection_id"], *row["correction_ids"]]
        ids += [m["maintenance_id"] for m in row["open_repairs"]]
        ids += [n["note_id"] for n in row["current_notes"]]

    if not rows and not notes:
        notes.append("no wells match")
    ids += _rule_citations(wells, [PRODUCING_RULE])
    return _result(kind, rows, ids, notes, truncated)


def inspection_series(asset_id: str, start: str, end: str) -> ToolResult:
    """Inspections of one well between start and end (inclusive), oldest first.

    Per inspection: date, ID, wellhead and ambient °C, °C above air, threshold, producing,
    spill detected, and the IDs of any corrections applied.
    """
    kind = "inspection_series"
    if note := _bad_dates(start, end):
        return _result(kind, [], [], [note])
    if not _known_wells([asset_id]):
        return _result(kind, [], [], [f"unknown well '{asset_id}'"])

    found = db.rows(
        f"""
        SELECT inspection_id, inspected_date, ambient_temp_c, wellhead_temp_c, temp_delta_c,
               producing_threshold_c, is_producing, spill_detected, spill_volume_bbl, correction_ids
        FROM inspections_effective
        WHERE asset_id = :a AND inspected_date BETWEEN :start AND :end
        ORDER BY inspected_at
        LIMIT {MAX_ROWS + 1}
        """,
        {"a": asset_id, "start": start, "end": end},
    )
    found, truncated = _cap(found)

    rows, ids, notes = [], [], []
    for r in found:
        row = {
            **r,
            "temp_delta_c": None if r["temp_delta_c"] is None else round(r["temp_delta_c"], 1),
            "is_producing": None if r["is_producing"] is None else bool(r["is_producing"]),
            "spill_detected": bool(r["spill_detected"]),
            "correction_ids": _correction_ids(r["correction_ids"]),
        }
        rows.append(row)
        ids += [row["inspection_id"], *row["correction_ids"]]

    if not rows:
        notes.append(f"no inspections of {asset_id} between {start} and {end}")
    elif any(r["is_producing"] is None for r in rows):
        notes.append(f"{asset_id}: no producing rule found")
    ids += _rule_citations([asset_id], [PRODUCING_RULE])
    return _result(kind, rows, ids, notes, truncated)


def downtime(
    start: str,
    end: str,
    asset_id: str | None = None,
    area: str | None = None,
    top_n: int | None = None,
) -> ToolResult:
    """Downtime days per well between start and end (inclusive), most first.

    Each inspection that finds a well not producing counts as `downtime_days_per_inspection`
    days (from the rules). Filter by well or area; `top_n` keeps the first N wells (ties at
    the cut are kept). Wells with no downtime are left out unless asked for by `asset_id`.
    """
    kind = "downtime"
    if note := _bad_dates(start, end):
        return _result(kind, [], [], [note])
    where, params = ["e.inspected_date BETWEEN :start AND :end"], {"start": start, "end": end}
    if area:
        area_id, note = _resolve_area(area)
        if note:
            return _result(kind, [], [], [note])
        where.append("e.area_id = :area_id")
        params["area_id"] = area_id
    if asset_id:
        if not _known_wells([asset_id]):
            return _result(kind, [], [], [f"unknown well '{asset_id}'"])
        where.append("e.asset_id = :asset_id")
        params["asset_id"] = asset_id

    found = db.rows(
        f"""
        SELECT e.asset_id, e.well_type, a.name AS area_name, e.inspection_id, e.inspected_date,
               e.is_producing, e.downtime_days, e.correction_ids
        FROM inspections_effective e
        JOIN areas a ON a.area_id = e.area_id
        WHERE {" AND ".join(where)}
        ORDER BY e.asset_id, e.inspected_at
        """,
        params,
    )

    per_well: dict[str, dict] = {}
    corrections: dict[str, list[str]] = {}
    no_rule: set[str] = set()
    for r in found:
        w = per_well.setdefault(
            r["asset_id"],
            {
                "asset_id": r["asset_id"],
                "well_type": r["well_type"],
                "area_name": r["area_name"],
                "downtime_days": 0,
                "down_inspections": 0,
                "down_dates": [],
                "down_inspection_ids": [],
            },
        )
        if r["is_producing"] is None or (not r["is_producing"] and r["downtime_days"] is None):
            no_rule.add(r["asset_id"])
            continue
        if not r["is_producing"]:
            w["downtime_days"] += r["downtime_days"]
            w["down_inspections"] += 1
            w["down_dates"].append(r["inspected_date"])
            w["down_inspection_ids"].append(r["inspection_id"])
            corrections.setdefault(r["asset_id"], []).extend(_correction_ids(r["correction_ids"]))

    rows = [w for w in per_well.values() if w["downtime_days"] > 0 or w["asset_id"] == asset_id]
    rows.sort(key=lambda w: (-w["downtime_days"], w["asset_id"]))
    if top_n is not None and top_n > 0 and len(rows) > top_n:
        cut = rows[top_n - 1]["downtime_days"]
        rows = [w for w in rows if w["downtime_days"] >= cut]
    rows, truncated = _cap(rows)

    notes = [f"{a}: no downtime rule found" for a in sorted(no_rule)]
    wells = [w["asset_id"] for w in rows]
    rule_rows = db.rows(
        """
        SELECT DISTINCT value, doc_id FROM well_rules
        WHERE rule_key = :key AND asset_id IN (SELECT value FROM json_each(:ids))
        ORDER BY value, doc_id
        """,
        {"key": DOWNTIME_RULE, "ids": json.dumps(wells or list(per_well))},
    )
    if rule_rows:
        rules = ", ".join(f"{_num(r['value'])} from {r['doc_id'] or 'user rule'}" for r in rule_rows)
        notes.insert(0, f"downtime = days per not-producing inspection ({rules})")
    if not rows:
        notes.append(f"no downtime between {start} and {end}")

    ids = []
    for w in rows:
        ids += w["down_inspection_ids"] + corrections.get(w["asset_id"], [])
    ids += _rule_citations(wells, [DOWNTIME_RULE, PRODUCING_RULE])
    return _result(kind, rows, ids, notes, truncated)
