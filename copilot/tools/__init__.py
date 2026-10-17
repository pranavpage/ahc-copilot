"""The agent's tools. A1 and A2 edit only their own module, never this file."""

from copilot.tools.assets import ASSET_TOOLS
from copilot.tools.base import ToolResult
from copilot.tools.compliance import COMPLIANCE_TOOLS
from copilot.tools.feedback import FEEDBACK_TOOLS
from copilot.tools.records import find_mentions, rca_due, repair_costs, search_docs, spills, well_records
from copilot.tools.status import downtime, inspection_series, well_status
from copilot.tools.visual import VisualSpec, show_visual
from copilot.tools.wells import identify_well

ALL_TOOLS = [
    identify_well,
    well_status,
    inspection_series,
    downtime,
    spills,
    well_records,
    repair_costs,
    rca_due,
    search_docs,
    find_mentions,
    *COMPLIANCE_TOOLS,
    *ASSET_TOOLS,
    show_visual,
]

# Tools that write (corrections, notes, rules). They read the user from the run config.
__all__ = ["ALL_TOOLS", "FEEDBACK_TOOLS", "ToolResult", "VisualSpec"]
