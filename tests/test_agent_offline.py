"""The agent with a scripted fake chat model. No network."""

import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from copilot import agent, api, results
from copilot.prompt import build_system_prompt
from copilot.tools import well_status
from copilot.tools.visual import show_visual


class ScriptedModel(GenericFakeChatModel):
    """Returns the scripted messages in order; tools are accepted and ignored."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


@pytest.fixture
def use_model(monkeypatch):
    """use_model(*messages): ask() runs on a fake model that replies with these messages."""

    def install(*messages: AIMessage, verify: bool = False):
        # The answer check is off by default: scripted answers are short. tests/test_verify.py tests it.
        model = ScriptedModel(messages=iter(messages))
        monkeypatch.setattr(agent, "get_llm", lambda: model)
        monkeypatch.setattr(agent, "VERIFY", verify)
        agent.get_graph.cache_clear()

    yield install
    agent.get_graph.cache_clear()


def test_ask_returns_tool_calls_citations_and_answer(use_model):
    use_model(
        AIMessage("", tool_calls=[call("well_status", {"asset_ids": ["WELL-0001"]}, "c1")]),
        AIMessage("WELL-0001 is not producing.", response_metadata={"model_name": "fake-model"}),
    )
    a = api.ask("Is WELL-0001 producing oil right now?", "U-201")

    assert a.error is None
    assert a.answer == "WELL-0001 is not producing."
    assert a.model == "fake-model"
    assert [(c.name, c.args) for c in a.tool_calls] == [("well_status", {"asset_ids": ["WELL-0001"]})]
    result_id = a.tool_calls[0].result_id
    assert result_id and results.get(result_id) is not None
    # Citations = the ids of the tool result (empty while the tool is a stub).
    assert a.citations == well_status(asset_ids=["WELL-0001"]).ids


def test_visual_block_and_turn_scoping(use_model):
    use_model(
        AIMessage("", tool_calls=[call("well_status", {"asset_ids": ["WELL-0001"]}, "c1")]),
        AIMessage("First answer."),
        AIMessage("Second answer, no tools."),
    )
    first = api.ask("Is WELL-0001 producing?", "U-201", thread_id="t1")
    rid = first.tool_calls[0].result_id

    # Second turn on the same thread: only this turn's tool calls are reported.
    second = api.ask("Thanks", "U-201", thread_id="t1")
    assert second.answer == "Second answer, no tools."
    assert second.tool_calls == [] and second.citations == []

    use_model(
        AIMessage("", tool_calls=[call("show_visual", {"type": "status_card", "title": "WELL-0001",
                                                       "source": rid, "fields": {"asset_id": "WELL-0001"}}, "v1")]),
        AIMessage("Here is the card."),
    )
    third = api.ask("Show its status card.", "U-201", thread_id="t2")
    assert third.error is None
    assert [b["type"] for b in third.blocks] == ["status_card"]
    assert third.blocks[0]["source"] == rid
    assert third.blocks[0]["rows"] == [r for r in results.get(rid) if r.get("asset_id") == "WELL-0001"]


def test_answer_written_next_to_the_visual_call(use_model):
    rid = results.put("well_status", [{"asset_id": "W-1"}])
    use_model(
        AIMessage("W-1 is producing.", tool_calls=[call("show_visual", {"type": "status_card", "title": "W-1",
                                                                        "source": rid, "fields": {}}, "v1")]),
        AIMessage(""),
    )
    a = api.ask("Is W-1 producing?", "U-201")
    assert a.answer == "W-1 is producing." and len(a.blocks) == 1


def test_invalid_show_visual_returns_error_to_model(use_model):
    use_model(
        AIMessage("", tool_calls=[call("show_visual", {"type": "pie_chart", "title": "x",
                                                       "source": "r_nope", "fields": {}}, "v1")]),
        AIMessage("Sorry, no visual."),
    )
    a = api.ask("Show a pie chart.", "U-201", thread_id="t3")
    assert a.error is None and a.blocks == [] and a.answer == "Sorry, no visual."

    messages = agent.get_graph().get_state({"configurable": {"thread_id": "t3"}}).values["messages"]
    tool_reply = next(m for m in messages if getattr(m, "tool_call_id", None) == "v1")
    assert "error" in json.loads(tool_reply.content)


def test_show_visual_validation():
    assert "error" in show_visual({"type": "pie_chart", "title": "t", "source": "r_x", "fields": {}})
    assert "unknown source" in show_visual({"type": "table", "title": "t", "source": "r_nope", "fields": {}})["error"]

    rid = results.put("well_status", [{"asset_id": "W-1", "producing": 1}, {"asset_id": "W-2", "producing": 0}])
    bad = show_visual({"type": "table", "title": "t", "source": rid, "fields": {"columns": ["nope"]}})
    assert "unknown columns" in bad["error"]

    ok = show_visual({"type": "table", "title": "t", "source": rid, "fields": {"columns": ["asset_id"]}})
    assert set(ok) == {"type", "title", "source", "fields", "rows"} and len(ok["rows"]) == 2
    card = show_visual({"type": "status_card", "title": "t", "source": rid, "fields": {"asset_id": "W-2"}})
    assert card["rows"] == [{"asset_id": "W-2", "producing": 0}]
    loose = show_visual({"type": "status_card", "title": "t", "source": rid, "fields": {"asset_id": "asset_id"}})
    assert len(loose["rows"]) == 2


def test_show_visual_fixes_column_name_keys():
    rid = results.put("spills", [{"area": "A", "month": "2026-01", "spill_count": 3},
                                 {"area": "B", "month": "2026-02", "spill_count": 1}])
    # The model sent column names as keys: they are mapped to x / y / value.
    heat = show_visual({"type": "heatmap", "title": "t", "source": rid,
                        "fields": {"month": "month", "spill_count": "spill_count"}})
    assert heat["fields"] == {"x": "month", "y": "area", "value": "spill_count"}
    # An extra key is dropped, not an error (a strict check made the model loop).
    m = results.put("spills", [{"asset_id": "W-1", "lat": 1.0, "lon": 2.0}])
    spot = show_visual({"type": "map", "title": "t", "source": m, "fields": {"asset_id": "asset_id", "lat": "lat", "lon": "lon"}})
    assert spot["fields"] == {"lat": "lat", "lon": "lon", "label": "asset_id"}
    # Nothing to infer from: an error that names the keys and the columns.
    bad = show_visual({"type": "line_chart", "title": "t", "source": rid, "fields": {}})
    assert "missing ['y']" in bad["error"] and "spill_count" in bad["error"]


def test_ask_never_raises(use_model):
    use_model()                                     # no scripted replies: the model call fails
    a = api.ask("hello", "U-201")
    assert a.error and a.answer == ""


def test_data_tool_wrapper_handles_stub_results(monkeypatch):
    from copilot.tools import ToolResult

    def fake_tool(asset_id: str) -> ToolResult:
        """Fake data tool.

        Owner: nobody.
        """
        return ToolResult(result_id="", kind="fake_tool", rows=[{"n": i} for i in range(80)],
                          ids=["X-1"], notes=["STUB"])

    tool = agent.data_tool(fake_tool)
    assert "Owner" not in tool.description
    msg = tool.invoke({"name": "fake_tool", "args": {"asset_id": "A"}, "id": "c1", "type": "tool_call"})
    body = json.loads(msg.content)
    assert body["result_id"] and msg.artifact["result_id"] == body["result_id"]
    assert body["row_count"] == 80 and len(body["rows"]) == agent.MODEL_ROWS
    assert len(results.get(body["result_id"])) == 80


def test_system_prompt_lists_data_from_db():
    from copilot import db

    prompt = build_system_prompt()
    assert db.today() in prompt
    for row in db.rows("SELECT area_id, name FROM areas"):
        assert row["area_id"] in prompt and row["name"] in prompt
    for row in db.rows("SELECT name, role FROM users"):
        assert row["name"] in prompt and row["role"] in prompt
    for row in db.rows("SELECT DISTINCT well_type FROM wells"):
        assert row["well_type"] in prompt
