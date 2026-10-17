"""The agent's tools. A1 and A2 edit only their own module, never this file."""

from copilot.tools.base import ToolResult
from copilot.tools.records import search_docs, spills, well_records
from copilot.tools.status import downtime, inspection_series, well_status
from copilot.tools.visual import VisualSpec, show_visual

ALL_TOOLS = [
    well_status,
    inspection_series,
    downtime,
    spills,
    well_records,
    search_docs,
    show_visual,
]

__all__ = ["ALL_TOOLS", "ToolResult", "VisualSpec"]
