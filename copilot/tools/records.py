"""Spills, per-well records and document search. Owner: A2.

Backed by the `spills` view, the record tables and `search_fts` + `rules` (db/schema.sql).
Dates are YYYY-MM-DD. `area` is a name ("Northeast Block 8") or an ID ("NE-08").
"""

from copilot.tools.base import ToolResult, stub


def spills(
    start: str | None = None,
    end: str | None = None,
    asset_id: str | None = None,
    area: str | None = None,
) -> ToolResult:
    """Real spills (after corrections) discovered between start and end (inclusive).

    Per spill: inspection ID, well, area, date, volume (bbl), class from the Spill Response
    SOP, reportable yes/no, the repair and report, and containment hours. Filter by well or area.

    Owner: A2.
    """
    return stub("spills")


def well_records(asset_id: str, start: str, end: str) -> ToolResult:
    """All records of one well between start and end (inclusive), oldest first.

    Repairs, regulatory events, notes valid in the period, and the compliance rows of the
    maintenance reports, each with its record ID.

    Owner: A2.
    """
    return stub("well_records")


def search_docs(query: str, asset_id: str | None = None, limit: int = 5) -> ToolResult:
    """Full-text search over manuals, SOPs, maintenance reports and notes.

    Returns the best `limit` sections with their citation (document and section, or record ID).
    `asset_id` limits well-specific text to one well; manuals and SOPs are always searched.

    Owner: A2.
    """
    return stub("search_docs")
