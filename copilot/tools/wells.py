"""Well lookup: turn what a user types ("0001", "well 1", "SW-23 Well 001") into a well ID.

`well_id` is also used by the agent to clean every `asset_id` / `asset_ids` argument before a
data tool runs, so "0001" works everywhere without an extra tool call.
"""

import json
import re

from copilot import db, results
from copilot.tools.base import ToolResult

# "WELL-0001", "well 1", "W-0001", "w1", "#1", "0001", "1"
_ID = re.compile(r"(?:well|w)?[\s\-_#]*0*(\d{1,4})", re.IGNORECASE)
_SPLIT = re.compile(r"\s*(?:,|;|\band\b|&)\s*", re.IGNORECASE)


def well_id(text: str) -> str | None:
    """'0001', 'well 1', 'W-1', 'WELL-0001' or a well name -> 'WELL-0001'; None if not a known well."""
    text = (text or "").strip()
    if not text:
        return None
    if m := _ID.fullmatch(text):
        candidate = f"WELL-{int(m.group(1)):04d}"
    else:
        found = db.rows("SELECT asset_id FROM wells WHERE lower(name) = lower(?)", (text,))
        candidate = found[0]["asset_id"] if found else None
    if candidate and db.rows("SELECT 1 FROM wells WHERE asset_id = ?", (candidate,)):
        return candidate
    return None


def identify_well(query: str) -> ToolResult:
    """Find wells from what the user typed, and return each well's metadata.

    `query`: one or more well references, separated by commas or "and": a well ID ("WELL-0001"),
    a bare number ("0001", "1", "well 1") or a well name ("SW-23 Well 001").
    Per well: ID, name, well type and its manual, area, team, person in charge, location,
    install date, recorded status (can be out of date) and the last inspection.
    """
    kind = "identify_well"
    parts = [p for p in _SPLIT.split(query or "") if p.strip()]
    ids, notes = [], []
    for p in parts:
        if a := well_id(p):
            ids.append(a)
        else:
            notes.append(f"no well matches '{p.strip()}'; well IDs look like WELL-0001")
    ids = list(dict.fromkeys(ids))

    found = {
        r["asset_id"]: r
        for r in db.rows(
            """
            SELECT w.asset_id, w.name, w.well_type, d.doc_id AS manual, w.area_id, a.name AS area_name,
                   t.name AS team_name, u.name AS in_charge_name, w.lat, w.lon, w.installed_on,
                   w.recorded_status, w.last_inspection_id, w.last_inspected_at
            FROM wells w
            LEFT JOIN areas a ON a.area_id = w.area_id
            LEFT JOIN teams t ON t.team_id = w.team_id
            LEFT JOIN users u ON u.user_id = w.in_charge_user_id
            LEFT JOIN documents d ON d.kind = 'well_manual' AND d.well_type = w.well_type
            WHERE w.asset_id IN (SELECT value FROM json_each(:ids))
            """,
            {"ids": json.dumps(ids)},
        )
    }
    rows = [found[a] for a in ids if a in found]
    if not parts:
        notes.append("no well given; well IDs look like WELL-0001")
    cites = [r["asset_id"] for r in rows] + [r["last_inspection_id"] for r in rows]
    return ToolResult(
        result_id=results.put(kind, rows),
        kind=kind,
        rows=rows,
        ids=list(dict.fromkeys(i for i in cites if i)),
        notes=notes,
    )

