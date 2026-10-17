"""Shared result type for the data tools."""

from pydantic import BaseModel

from copilot import results

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
