"""Shared result type and helpers for the data tools."""

import json

from pydantic import BaseModel

from copilot import db, results

STUB_NOTE = "STUB: not implemented"


class ToolResult(BaseModel):
    """What every data tool returns to the model.

    The rows are also stored in `copilot.results` under `result_id`, so a visual can refer
    to them without the model copying numbers.
    """

    result_id: str
    kind: str                  # the tool name, e.g. "well_status"
    rows: list[dict]
    ids: list[str]             # record IDs for citations: INS-…, MNT-…, REG-…, CTX-…, COR-…, doc sections
    notes: list[str]           # warnings: "no rule found", "unknown area; valid: …"
    truncated: bool = False    # True if rows were cut to keep the result small


def stub(kind: str) -> ToolResult:
    """Empty result for a tool that is not implemented yet. Never raises."""
    return ToolResult(result_id=results.put(kind, []), kind=kind, rows=[], ids=[], notes=[STUB_NOTE])


def run_context(config: dict | None) -> dict:
    """The run's configurable, with `user_id` filled from the `x-user-id` header on the LangGraph
    server (the server copies x-* request headers into configurable; the web UI sends it)."""
    c = dict((config or {}).get("configurable") or {})
    # The server also sets user_id = "" (its auth user, empty without auth), so the header wins.
    c["user_id"] = c.get("x-user-id") or c.get("user_id") or None
    return c


def fmt_value(v, field: str | None = None) -> str:
    """A measured value as people write it: 24.0 -> '24.0', 5.4 -> '5.4', None -> 'none'.
    `spill_detected` is a flag: 1 -> '1'."""
    if v is None:
        return "none"
    if field == "spill_detected":
        return str(int(v))
    v = float(v)
    return f"{v:.1f}" if abs(v * 10 - round(v * 10)) < 1e-9 else f"{v:g}"


def _as_measured(c: dict) -> dict:
    """SQLite NUMERIC stores 41.0 as 41; give measured values back as floats."""
    if c["field"] != "spill_detected":
        for k in ("original_value", "corrected_value"):
            if c[k] is not None:
                c[k] = float(c[k])
    return c


def correction_details(correction_ids: list[str]) -> list[dict]:
    """Who corrected what, for citations: one row per correction ID, in the given order."""
    if not correction_ids:
        return []
    found = db.rows(
        """
        SELECT c.correction_id, c.source, c.target_id, c.field, c.original_value, c.corrected_value,
               u.name AS corrected_by, c.reason, substr(c.created_at, 1, 10) AS date
        FROM corrections c LEFT JOIN users u ON u.user_id = c.author_user_id
        WHERE c.correction_id IN (SELECT value FROM json_each(:ids))
        """,
        {"ids": json.dumps(correction_ids)},
    )
    by_id = {r["correction_id"]: _as_measured(r) for r in found}
    return [by_id[c] for c in correction_ids if c in by_id]


def correction_note(c: dict) -> str:
    """'INS-0164-0205 wellhead_temp_c corrected 24.0 -> 41.0 by Michael Turner (2026-10-16): …'"""
    old, new = fmt_value(c["original_value"], c["field"]), fmt_value(c["corrected_value"], c["field"])
    return (f"{c['target_id']} {c['field']} corrected {old} -> {new} "
            f"by {c['corrected_by'] or 'unknown'} ({c['date']}): {c['reason']}")


def user_rule_cite(rule_id: int, author_user_id: str | None) -> str:
    """'user rule 26 by Michael Turner'."""
    name = db.rows("SELECT name FROM users WHERE user_id = ?", (author_user_id,)) if author_user_id else []
    return f"user rule {rule_id}" + (f" by {name[0]['name']}" if name else "")
