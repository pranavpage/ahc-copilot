"""Contracts shared by the parallel tasks (TASKS.md). No LLM or network calls."""

import inspect

import pytest

from copilot import api, config, db, results
from copilot.tools import ALL_TOOLS, ToolResult, VisualSpec
from copilot.tools import records, status, visual
from evals.cases import EvalCase, load_cases

DATA_TOOLS = ALL_TOOLS[:-1]

# Minimal valid arguments for each data tool.
ARGS = {
    "identify_well": {"query": "WELL-0001"},
    "well_status": {},
    "inspection_series": {"asset_id": "WELL-0001", "start": "2026-07-01", "end": "2026-10-16"},
    "downtime": {"start": "2026-07-01", "end": "2026-10-16"},
    "spills": {},
    "well_records": {"asset_id": "WELL-0001", "start": "2026-07-01", "end": "2026-10-16"},
    "search_docs": {"query": "spill"},
}


def test_modules_import():
    for m in (api, config, db, results, records, status, visual):
        assert m.__doc__


def test_all_tools_order():
    assert [t.__name__ for t in ALL_TOOLS] == [
        "identify_well", "well_status", "inspection_series", "downtime",
        "spills", "well_records", "search_docs", "show_visual",
    ]


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.__name__)
def test_tools_typed_and_documented(tool):
    sig = inspect.signature(tool)
    assert tool.__doc__
    assert all(p.annotation is not inspect.Parameter.empty for p in sig.parameters.values())
    assert sig.return_annotation is not inspect.Signature.empty


@pytest.mark.parametrize("tool", DATA_TOOLS, ids=lambda t: t.__name__)
def test_data_tools_return_tool_result(tool):
    r = tool(**ARGS[tool.__name__])
    assert isinstance(r, ToolResult)
    assert r.kind == tool.__name__
    assert results.get(r.result_id) == r.rows


def test_show_visual_returns_dict():
    spec = VisualSpec(type="table", title="t", source="r_0000", fields={})
    assert isinstance(visual.show_visual(spec), dict)


def test_results_store():
    rid = results.put("x", [{"a": 1}])
    assert rid.startswith("r_") and results.get(rid) == [{"a": 1}]
    results.clear()
    with pytest.raises(KeyError):
        results.get(rid)


def test_ask_returns_answer():
    assert isinstance(api.ask("hello", "U-201"), api.Answer)


def test_load_cases():
    cases = load_cases()
    assert cases and all(isinstance(c, EvalCase) for c in cases)
    assert cases[0].id == "Q1" and cases[0].visual == "status_card"


def test_case_needs_question_or_turns():
    with pytest.raises(ValueError):
        EvalCase(id="bad")
    with pytest.raises(ValueError):
        EvalCase(id="bad", question="q", turns=[{"user_id": "U-201", "message": "m"}])


def test_db_today():
    assert db.today() == "2026-10-16"


def test_db_read_only():
    with pytest.raises(Exception, match="readonly"):
        db.connect().execute("DELETE FROM settings")
