"""The answer check (copilot/verify.py) and the verify step of the agent. No network."""

from langchain_core.messages import AIMessage, HumanMessage

from copilot import api, verify
from copilot.agent import data_tool
from copilot.tools import find_mentions, repair_costs
from tests.test_agent_offline import call, use_model  # noqa: F401 - fixture


def turn(tool, args: dict, answer: str) -> list:
    """A turn: the question, one tool call with its real result, then the answer."""
    msg = data_tool(tool).invoke({"name": tool.__name__, "args": args, "id": "c1", "type": "tool_call"})
    return [HumanMessage("q"), AIMessage("", tool_calls=[call(tool.__name__, args, "c1")]), msg, AIMessage(answer)]


COSTS = (repair_costs, {"asset_ids": ["WELL-0121", "WELL-0138", "WELL-0107"], "start": "2026-01-01", "end": "2026-10-16"})


def test_a_grounded_answer_passes():
    r = verify.check(turn(*COSTS, "WELL-0121: USD 25,794; WELL-0138: USD 46,942; WELL-0107: USD 5,176."))
    assert r["status"] == "passed", r["problems"]
    assert r["checked"]["ids"] == 3 and r["checked"]["numbers"] == 3 and r["checked"]["lists"] == 1


def test_wrong_numbers_unknown_ids_and_missing_items_fail():
    r = verify.check(turn(*COSTS, "WELL-0121: USD 26,550; WELL-0138: USD 42,775. See MNT-0999-001."))
    text = " ".join(r["problems"])
    assert r["status"] == "failed"
    assert "26,550" in text and "42,775" in text          # numbers in no tool result
    assert "MNT-0999-001" in text                         # ID in no tool result
    assert "missing: WELL-0107" in text                   # list not complete


def test_find_mentions_answer_must_name_every_group_and_the_totals():
    short = verify.check(turn(find_mentions, {"terms": ["test"]}, "The annual integrity test (RC-02)."))
    assert short["status"] == "failed"
    assert any("pressure test" in p and "gas test" in p for p in short["problems"])
    assert any("totals" in p for p in short["problems"])


def test_say_so_notes_must_be_stated():
    from copilot.tools import downtime

    msgs = turn(downtime, {"start": "2025-01-01", "end": "2025-12-31", "asset_id": "WELL-0001"},
                "WELL-0001 was down 21 days in 2025.")
    r = verify.check(msgs)
    assert r["status"] == "failed" and any("51.6" in p and "MNT-0001-021" in p for p in r["problems"])


def test_agent_sends_a_failed_answer_back_once(use_model):  # noqa: F811
    use_model(
        AIMessage("", tool_calls=[call("repair_costs", COSTS[1], "c1")]),
        AIMessage("WELL-0121 cost USD 26,550."),                       # wrong number, 1 of 3 wells
        AIMessage("WELL-0121: USD 25,794; WELL-0138: USD 46,942; WELL-0107: USD 5,176."),
        verify=True,
    )
    a = api.ask("What have repairs cost this year for WELL-0121, WELL-0138 and WELL-0107?", "U-201", "t-verify")
    assert a.error is None
    assert a.answer.startswith("WELL-0121: USD 25,794")
    assert a.verification["status"] == "passed" and a.verification["round"] == 2
    assert [c.name for c in a.tool_calls] == ["repair_costs"]
    kinds = [s["kind"] + (":" + s["name"] if s.get("name") else "") for s in a.trace]
    assert kinds.count("tool:verify_answer") == 2


def test_agent_shows_the_problems_when_the_second_answer_also_fails(use_model):  # noqa: F811
    use_model(
        AIMessage("", tool_calls=[call("repair_costs", COSTS[1], "c1")]),
        AIMessage("WELL-0121 cost USD 26,550."),
        AIMessage("WELL-0121 cost USD 26,551."),
        verify=True,
    )
    a = api.ask("Repair costs?", "U-201", "t-verify-2")
    assert a.answer == "WELL-0121 cost USD 26,551."
    assert a.verification["status"] == "failed" and a.verification["problems"]
