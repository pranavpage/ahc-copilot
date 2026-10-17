"""Private per-user preferences: set_preference, the prompt, and the rows of data tools. No network."""

import json

from langchain_core.messages import AIMessage

from copilot import agent, api, db, memory, results
from copilot.prompt import build_system_prompt
from tests.test_agent_offline import call, use_model  # noqa: F401 - fixture

PREF = "sort wells by area, then by well ID, and show costs in thousands of dollars"


def test_set_preference_is_private_and_in_later_prompts(use_model):  # noqa: F811
    use_model(
        AIMessage("", tool_calls=[call("set_preference", {"preference": PREF}, "p1")]),
        AIMessage("Saved for you only: wells by area then ID, costs in $k."),
    )
    a = api.ask("Just for me: whenever you list wells, sort them by area and then by well ID, "
                "and show costs in thousands of dollars.", "U-201", "t-pref-1")
    assert a.error is None
    msgs = agent.get_graph().get_state({"configurable": {"thread_id": "t-pref-1"}}).values["messages"]
    reply = json.loads(next(m for m in msgs if getattr(m, "tool_call_id", None) == "p1").content)
    assert reply["rows"], reply
    assert reply["rows"][0]["user_id"] == "U-201"            # from the config, not the model

    stored = db.rows("SELECT user_id, preference, conversation_id, status FROM user_preferences "
                     "WHERE conversation_id = 't-pref-1'")
    assert stored == [{"user_id": "U-201", "preference": PREF, "conversation_id": "t-pref-1", "status": "active"}]

    assert PREF in build_system_prompt("U-201")               # a later session of the same user
    assert PREF not in build_system_prompt("U-301")           # never another user
    assert PREF not in build_system_prompt(None)
    assert memory.preference_settings("U-201") == {"sort_wells_by_area": True, "costs_in_thousands": True}
    assert memory.preference_settings("U-301") == {"sort_wells_by_area": False, "costs_in_thousands": False}

    # A later session: the data tool rows follow the preference (the user comes from the run config).
    use_model(
        AIMessage("", tool_calls=[call("repair_costs", {"asset_ids": ["WELL-0121", "WELL-0001"],
                                                        "start": "2025-01-01", "end": "2026-10-16"}, "r1")]),
        AIMessage("Done."),
    )
    api.ask("What have repairs cost on WELL-0121 and WELL-0001?", "U-201", "t-pref-2")
    msgs = agent.get_graph().get_state({"configurable": {"thread_id": "t-pref-2"}}).values["messages"]
    rows = json.loads(next(m for m in msgs if getattr(m, "tool_call_id", None) == "r1").content)["rows"]
    assert [r["asset_id"] for r in rows] == ["WELL-0121", "WELL-0001"]      # Northeast Block 7 first
    assert all("cost_total_k_usd" in r for r in rows)

    pref_id = memory.preferences("U-201")[-1]["pref_id"]
    assert not memory.retract_preference("U-301", pref_id)    # not theirs
    assert memory.retract_preference("U-201", pref_id)
    assert PREF not in build_system_prompt("U-201")


def test_set_preference_needs_a_known_user(use_model):  # noqa: F811
    use_model(
        AIMessage("", tool_calls=[call("set_preference", {"preference": "costs in $k"}, "p1")]),
        AIMessage("Who are you?"),
    )
    api.ask("From now on show costs in $k.", "U-999", "t-pref-anon")
    assert not db.rows("SELECT 1 FROM user_preferences WHERE conversation_id = 't-pref-anon'")


def test_apply_preferences_sorts_wells_and_adds_costs_in_thousands():
    rows = [{"asset_id": "WELL-0150", "install_cost_usd": 12345.0},
            {"asset_id": "WELL-0001", "install_cost_usd": None},
            {"asset_id": "WELL-0002", "install_cost_usd": 800}]
    areas = {r["asset_id"]: r["area_id"] for r in db.rows("SELECT asset_id, area_id FROM wells")}
    out, notes = memory.apply_preferences(rows, {"sort_wells_by_area": True, "costs_in_thousands": True})
    names = {a["area_id"]: a["name"] for a in db.rows("SELECT area_id, name FROM areas")}
    expected = sorted(rows, key=lambda r: (names[areas[r["asset_id"]]], r["asset_id"]))
    assert [r["asset_id"] for r in out] == [r["asset_id"] for r in expected]
    by_id = {r["asset_id"]: r for r in out}
    assert by_id["WELL-0150"]["install_cost_k_usd"] == 12.3 and by_id["WELL-0001"]["install_cost_k_usd"] is None
    assert len(notes) == 2
    # Ranked rows keep their order; nothing to apply = unchanged.
    ranked = [{"rank": 1, "asset_id": "WELL-0150"}, {"rank": 2, "asset_id": "WELL-0001"}]
    assert memory.apply_preferences(ranked, {"sort_wells_by_area": True}) == (ranked, [])
    assert memory.apply_preferences(rows, {}) == (rows, [])


def test_data_tool_applies_the_users_preferences(monkeypatch):
    monkeypatch.setattr(memory, "preference_settings",
                        lambda user_id: {"costs_in_thousands": user_id == "U-201", "sort_wells_by_area": False})

    def costs(*, config=None):
        """Fake cost tool."""
        rows = [{"asset_id": "WELL-0001", "cost_total_usd": 25794.0}]
        from copilot.tools import ToolResult
        return ToolResult(result_id=results.put("costs", rows), kind="costs", rows=rows, ids=[], notes=[])

    tool = agent.data_tool(costs)
    mine = json.loads(tool.func(config={"configurable": {"user_id": "U-201"}})[0])
    assert mine["rows"][0]["cost_total_k_usd"] == 25.8
    assert results.get(mine["result_id"])[0]["cost_total_k_usd"] == 25.8     # visuals see it too
    other = json.loads(tool.func(config={"configurable": {"user_id": "U-301"}})[0])
    assert "cost_total_k_usd" not in other["rows"][0]
