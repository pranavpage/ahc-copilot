"""The show_visual tool. Owner: D. G replaces VisualSpec with the full catalog (PLAN-UI.md)."""

import re
from typing import Literal

from pydantic import BaseModel, ValidationError

from copilot import results

VisualType = Literal["status_card", "table", "line_chart", "bar_chart", "map", "heatmap"]

# Keys of `fields` whose values name columns of the source rows.
COLUMN_KEYS = {"x", "y", "category", "value", "lat", "lon", "label", "color_by", "columns", "popup"}

# The `fields` keys of each type: (required, optional). The same table is in the system prompt.
FIELD_KEYS: dict[str, tuple[set[str], set[str]]] = {
    "status_card": (set(), {"asset_id"}),
    "table": ({"columns"}, set()),
    "line_chart": ({"x", "y"}, {"unit"}),
    "bar_chart": ({"category", "value"}, {"unit"}),
    "map": ({"lat", "lon"}, {"label", "color_by", "popup"}),
    "heatmap": ({"x", "y"}, {"value"}),      # no value = count the rows per cell
}
FIELD_HINTS = {
    "status_card": '{"asset_id": "<the well ID itself>"}',
    "table": '{"columns": ["<column>", ...]}',
    "line_chart": '{"x": "<date column>", "y": ["<column>"], "unit": "<unit>"}',
    "bar_chart": '{"category": "<column>", "value": "<column>", "unit": "<unit>"}',
    "map": '{"lat": "<column>", "lon": "<column>", "label": "<column>"}',
    "heatmap": '{"x": "<column>", "y": "<column>", "value": "<column>"}',
}


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


def _normalize(kind: str, fields: dict, rows: list[dict], columns: set[str]) -> dict:
    """The fields of `kind`: unknown keys are dropped, missing keys are inferred from the columns.

    Models often send {"<column>": "<column>"} instead of {"x": ..., "y": ...}; a strict check makes
    them repeat the same spec until the recursion limit. The columns named anywhere in `fields`
    are used first, then the other columns of the rows.
    """
    required, optional = FIELD_KEYS[kind]
    out = {k: v for k, v in fields.items() if k in required | optional and _column_names(v) or k == "unit"}
    named = list(dict.fromkeys(c for v in fields.values() for c in _column_names(v) if c in columns))
    every = named + [c for c in (rows[0] if rows else {}) if c not in named]

    def values(c):
        return [r.get(c) for r in rows if r.get(c) is not None]

    def numeric(c):
        v = values(c)
        return bool(v) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)

    def date(c):
        v = values(c)
        return bool(v) and all(isinstance(x, str) and re.match(r"\d{4}-\d{2}", x) for x in v)

    def first(test, pool=every, skip=()):
        return next((c for c in pool if test(c) and c not in skip), None)

    guesses = {
        "table": {"columns": named or None},
        "line_chart": {"x": first(date), "y": [c for c in named if numeric(c)] or None},
        "bar_chart": {"category": first(lambda c: not numeric(c) and not date(c)),
                      "value": first(numeric, named) or first(numeric)},
        "map": {"lat": "lat" if "lat" in columns else None, "lon": "lon" if "lon" in columns else None,
                "label": "asset_id" if "asset_id" in columns else None},
        "heatmap": {"x": first(date), "value": first(numeric, named)},
    }.get(kind, {})
    for key, guess in guesses.items():
        if key not in out and guess:
            out[key] = guess
    if kind == "heatmap" and "y" not in out:
        y = first(lambda c: not numeric(c), skip=_column_names(out.get("x")))
        if y:
            out["y"] = y
    return out


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

    columns = set().union(*(r.keys() for r in rows)) if rows else set()
    fields = _normalize(spec.type, spec.fields, rows, columns)
    missing = sorted(FIELD_KEYS[spec.type][0] - fields.keys())
    if missing:
        return {"error": f"{spec.type} needs fields {FIELD_HINTS[spec.type]} (missing {missing}). Columns of "
                         f"{spec.source}: {sorted(columns)}. Fix it once; if it fails again, answer without a visual."}
    spec = spec.model_copy(update={"fields": fields})

    if rows:
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
