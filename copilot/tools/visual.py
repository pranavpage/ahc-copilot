"""The show_visual tool. Owner: D. G replaces VisualSpec with the full catalog (PLAN-UI.md)."""

from typing import Literal

from pydantic import BaseModel

from copilot.tools.base import STUB_NOTE

VisualType = Literal["status_card", "table", "line_chart", "bar_chart", "map", "heatmap"]


class VisualSpec(BaseModel):
    """One visual. Data by reference: `source` is a result_id from a data tool."""

    type: VisualType
    title: str
    source: str                # result_id
    fields: dict               # which columns to use, e.g. {"x": "date", "y": ["temp_delta_c"]}


def show_visual(spec: VisualSpec) -> dict:
    """Show one visual with the answer.

    Returns the filled block: the spec plus the rows of `source` from the result store, or
    the validation error for the model to fix.

    Owner: D.
    """
    return {**spec.model_dump(), "rows": [], "notes": [STUB_NOTE]}
