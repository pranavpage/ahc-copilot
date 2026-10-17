"""Private memory: the user in the prompt, the conversation index, recall. No network."""

import json

from langchain_core.messages import AIMessage

from copilot import api, db, memory
from copilot.prompt import build_system_prompt
from tests.test_agent_offline import call, use_model  # noqa: F401 - fixture


def test_prompt_names_the_user():
    prompt = build_system_prompt("U-201")
    assert "Michael Turner (U-201), production supervisor, team Northeast Production" in prompt
    assert "Northeast Block 7 (NE-07)" in prompt and "recall_conversations" in prompt
    assert "not identified (user ID 'U-999'" in build_system_prompt("U-999")
    assert "not identified (no user ID)" in build_system_prompt()


def test_prompt_lists_period_starts():
    prompt = build_system_prompt("U-201")
    assert "last 13 weeks 2026-07-17" in prompt and "last 90 days 2026-07-18" in prompt
    assert "last 4 months 2026-06-16" in prompt and "this year 2026-01-01" in prompt


def test_entities_in_order_of_mention():
    text = "Top 3 in Northeast Block 7: WELL-0121 (49 days), WELL-0138, WELL-0107. MNT-0121-001. WELL-0121 again."
    assert memory.entities(text) == [("area", "NE-07"), ("well", "WELL-0121"), ("well", "WELL-0138"),
                                     ("well", "WELL-0107"), ("maintenance", "MNT-0121-001")]


def test_remember_and_recall_are_private():
    memory.remember("t-mem-1", "U-201", "Top 3 downtime in NE-07?", "WELL-0121, WELL-0138 and WELL-0107.")
    memory.remember("t-mem-1", "U-201", "And the next one?", "WELL-0119 at 28 days.")
    memory.remember("t-mem-1", "U-202", "Hijack the thread", "WELL-0001.")    # not the owner: ignored
    memory.remember("t-mem-2", "U-999", "Unknown user", "WELL-0001.")         # unknown user: ignored

    mine = memory.recall("U-201", limit=100)
    conv = next(c for c in mine if c["conversation_id"] == "t-mem-1")
    assert conv["title"] == "Top 3 downtime in NE-07?"
    assert [t["wells"] for t in conv["turns"]] == [["WELL-0121", "WELL-0138", "WELL-0107"], ["WELL-0119"]]
    assert all(c["conversation_id"] != "t-mem-1" for c in memory.recall("U-202", limit=100))
    assert memory.recall("U-201", exclude_thread_id="t-mem-1", limit=100) == [
        c for c in mine if c["conversation_id"] != "t-mem-1"]
    assert memory.recall("U-201", query="WELL-0119")[0]["conversation_id"] == "t-mem-1"
    assert all(c["conversation_id"] != "t-mem-1" for c in memory.recall("U-201", query="spills", limit=100))
    assert not db.rows("SELECT 1 FROM conversations WHERE conversation_id = 't-mem-2'")


def test_agent_remembers_and_recalls_per_user(use_model):  # noqa: F811
    use_model(
        AIMessage("", tool_calls=[call("downtime", {"start": "2026-06-16", "end": "2026-10-16",
                                                    "area": "NE-07", "top_n": 3}, "c1")]),
        AIMessage("The top 3: WELL-0121 (49 days), WELL-0138 (42) and WELL-0107 (42)."),
        # Day 2, new thread: the model calls recall_conversations.
        AIMessage("", tool_calls=[call("recall_conversations", {}, "c2")]),
        AIMessage("Those were WELL-0121, WELL-0138 and WELL-0107."),
        # Another user asks the same: recall returns nothing.
        AIMessage("", tool_calls=[call("recall_conversations", {}, "c3")]),
        AIMessage("I have no earlier conversation with you."),
    )
    api.ask("Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months?", "U-201", "t-day1")
    stored = db.rows("SELECT entity_id FROM conversation_entities WHERE conversation_id = 't-day1' "
                     "AND entity_type = 'well' ORDER BY rank")
    assert [r["entity_id"] for r in stored] == ["WELL-0121", "WELL-0138", "WELL-0107"]

    from copilot import agent
    graph = agent.get_graph()

    def tool_reply(thread, call_id):
        msgs = graph.get_state({"configurable": {"thread_id": thread}}).values["messages"]
        return json.loads(next(m for m in msgs if getattr(m, "tool_call_id", None) == call_id).content)

    a = api.ask("For the three wells we discussed yesterday, what have repairs cost?", "U-201", "t-day2")
    assert a.error is None
    rows = tool_reply("t-day2", "c2")["rows"]
    assert rows[0]["conversation_id"] == "t-day1"          # the current thread is left out
    assert rows[0]["turns"][0]["wells"] == ["WELL-0121", "WELL-0138", "WELL-0107"]

    api.ask("For the three wells we discussed yesterday, what have repairs cost?", "U-202", "t-jess")
    body = tool_reply("t-jess", "c3")
    assert all(r["conversation_id"] not in ("t-day1", "t-day2") for r in body["rows"])


def test_my_wells_are_the_wells_of_my_team():
    """A well's own team beats its area's team (test data: 10 wells of SW-24 moved to Southeast)."""
    import os
    import sqlite3
    import tempfile
    from contextlib import closing
    from pathlib import Path

    import pytest

    from copilot.config import get_settings

    test_db = Path(__file__).resolve().parents[1] / "data" / "copilot.db"
    if not test_db.exists():
        pytest.skip("data/copilot.db not built")
    old = os.environ.get("DB_PATH")
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "copilot.db"
        with closing(sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)) as a, closing(sqlite3.connect(dst)) as b:
            a.backup(b)
        os.environ["DB_PATH"] = str(dst)
        get_settings.cache_clear()
        try:
            olivia = memory.user_profile("U-501")          # Southeast Production
            areas = {a["area_id"]: a for a in olivia["areas"]}
            moved = db.rows("SELECT COUNT(*) AS n FROM wells WHERE team_id = 'TEAM-SE' AND area_id = 'SW-24'")[0]["n"]
            assert moved > 0 and areas["SW-24"]["team_wells"] == moved
            assert olivia["team_wells"] == db.rows("SELECT COUNT(*) AS n FROM wells WHERE team_id = 'TEAM-SE'")[0]["n"]
            emily = memory.user_profile("U-101")           # Southwest Production keeps the rest of SW-24
            sw24 = next(a for a in emily["areas"] if a["area_id"] == "SW-24")
            assert sw24["team_wells"] == sw24["area_wells"] - moved
            assert f"{moved} of its" in build_system_prompt("U-501")
        finally:
            if old is None:
                os.environ.pop("DB_PATH", None)
            else:
                os.environ["DB_PATH"] = old
            get_settings.cache_clear()
