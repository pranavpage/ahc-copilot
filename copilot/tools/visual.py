"""The show_visual tool. Owner: D. G replaces VisualSpec with the full catalog (PLAN-UI.md)."""

from typing import Literal

from pydantic import BaseModel, ValidationError

from copilot import results

VisualType = Literal["status_card", "table", "line_chart", "bar_chart", "map", "heatmap"]

# Keys of `fields` whose values name columns of the source rows.
COLUMN_KEYS = {"x", "y", "category", "value", "lat", "lon", "label", "color_by", "columns", "popup"}


class VisualSpec(BaseModel):
    """One visual. Data by reference: `source` is a result_id from a data tool."""

    type: VisualType
    title: str
    source: str                # result_id
    fields: dict               # which columns to use, e.g. {"x": "date", "y": ["temp_delta_c"]}


def _column_names(value) -> list[str]:
    """Column names in a `fields` value: a name, a list of names, or [{"field": name}, ...]."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return _column_names(value.get("field"))
    if isinstance(value, list):
        return [name for v in value for name in _column_names(v)]
    return []


def show_visual(spec: VisualSpec | dict) -> dict:
    """Show one visual with the answer.

    Returns the filled block: the spec plus the rows of `source` from the result store, or
    {"error": ...} for the model to fix. Never raises.
    """
    try:
        spec = VisualSpec.model_validate(spec)
    except ValidationError as e:
        return {"error": f"invalid visual spec: {e}"}
    try:
        rows = results.get(spec.source)
    except KeyError:
        return {"error": f"unknown source '{spec.source}'; use the result_id of a data tool result"}

    if rows:
        columns = set().union(*(r.keys() for r in rows))
        unknown = [c for k in COLUMN_KEYS & spec.fields.keys() for c in _column_names(spec.fields[k])
                   if c not in columns]
        if unknown:
            return {"error": f"unknown columns {unknown} in fields; columns of {spec.source}: {sorted(columns)}"}

    # A card shows one well: keep its row. If no row matches (e.g. the model wrote the column
    # name instead of the well ID), keep the rows as they are.
    asset_id = spec.fields.get("asset_id")
    if spec.type == "status_card" and asset_id:
        rows = [r for r in rows if r.get("asset_id") == asset_id] or rows

    return {**spec.model_dump(), "rows": rows}
