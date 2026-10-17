"""Well status, inspection history and downtime. Owner: A1.

Backed by the views `well_status_now` and `inspections_effective` (db/schema.sql).
Dates are YYYY-MM-DD. `area` is a name ("Northeast Block 8") or an ID ("NE-08").
"""

from copilot.tools.base import ToolResult, stub


def well_status(
    asset_ids: list[str] | None = None,
    area: str | None = None,
    not_producing_only: bool = False,
) -> ToolResult:
    """Current status of wells, from each well's latest inspection.

    Per well: producing yes/no, °C above air vs. the threshold, the last inspection (ID, date,
    inspector, method), the recorded status and whether it is out of date, open repairs and
    valid notes that explain a stop. Filter by wells, by area, or to wells not producing.

    Owner: A1.
    """
    return stub("well_status")


def inspection_series(asset_id: str, start: str, end: str) -> ToolResult:
    """Inspections of one well between start and end (inclusive), oldest first.

    Per inspection: date, ID, wellhead and ambient °C, °C above air, threshold, producing,
    spill detected, and the IDs of any corrections applied.

    Owner: A1.
    """
    return stub("inspection_series")


def downtime(
    start: str,
    end: str,
    asset_id: str | None = None,
    area: str | None = None,
    top_n: int | None = None,
) -> ToolResult:
    """Downtime days per well between start and end (inclusive), most first.

    Each inspection that finds a well not producing counts as `downtime_days_per_inspection`
    days (from the rules). Filter by well or area; `top_n` keeps the first N wells.

    Owner: A1.
    """
    return stub("downtime")
