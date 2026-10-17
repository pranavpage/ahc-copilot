"""Eval metrics and runner. No LLM calls: ask() is evals.fake or a recorder."""

import json
import os
from types import SimpleNamespace

import pytest

from copilot.api import Answer
from copilot.config import get_settings
from evals import fake
from evals.cases import EvalCase, load_cases
from evals.metrics import FactRecall, VisualMatch, make_test_case
from evals.runner import Runner, get_ask, isolated_db, run_case


def tc(answer="", citations=(), blocks=()):
    return make_test_case("q", Answer(answer=answer, blocks=list(blocks), citations=list(citations),
                                      tool_calls=[], model="m", error=None))


def recall(must_include, must_not_include=(), **kw):
    m = FactRecall(must_include, list(must_not_include))
    m.measure(tc(**kw))
    return m


def test_fact_recall_normalises_numbers():
    assert recall(["5000", "-3.2", "ryan brooks"], answer="5,000 bbl, −3.2 °C, Ryan Brooks").success
    assert recall(["5,000"], answer="5000 bbl").success
    assert recall(["1234567"], answer="1,234,567").success


def test_fact_recall_does_not_match_inside_numbers():
    assert not recall(["3.2"], answer="13.2 °C").success
    assert not recall(["3.2"], answer="3.25 °C").success
    assert not recall(["21"], answer="in 2021").success
    assert recall(["3.2"], answer="only 3.2.").success


def test_fact_recall_alternatives_and_partial_score():
    m = recall([["21 days", "twenty-one days"], "WELL-0001"], answer="Down twenty-one days.")
    assert m.score == 0.5 and not m.success
    assert "WELL-0001" in m.reason and "twenty-one" not in m.reason


def test_fact_recall_searches_citations_and_blocks():
    m = recall(["INS-0001-0203", "15.1"], citations=["INS-0001-0203"],
               blocks=[{"type": "table", "rows": [{"t": 15.1}]}])
    assert m.success


def test_fact_recall_must_not_include_fails():
    m = recall(["WELL-0164"], ["WELL-0001"], answer="WELL-0164 and well-0001")
    assert m.score == 1.0 and not m.success
    assert "forbidden found: WELL-0001" in m.reason


@pytest.mark.parametrize("visual", [None, "none"])
def test_visual_match_none_passes(visual):
    m = VisualMatch(visual)
    m.measure(tc())
    assert m.success


def test_visual_match_type():
    m = VisualMatch("table")
    m.measure(tc(blocks=[{"type": "status_card"}]))
    assert not m.success and "table" in m.reason and "status_card" in m.reason
    m.measure(tc(blocks=[{"type": "status_card"}, {"type": "table"}]))
    assert m.success


def test_get_ask_from_env(monkeypatch):
    monkeypatch.setenv("EVAL_ASK", "evals.fake:ask")
    assert get_ask() is fake.ask


def test_fake_q1_passes_other_case_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_ASK", "evals.fake:ask")
    q1 = next(c for c in load_cases() if c.id == "Q1")
    other = EvalCase(id="Q2", question="Which wells in Northeast Block 8 are not producing?",
                     visual="table", must_include=["WELL-0164"])
    log = tmp_path / "run.jsonl"
    r = Runner([q1, other], get_ask(), log_path=log)
    assert r.result("Q1").passed
    res = r.result("Q2")
    assert not res.passed
    assert "missing: WELL-0164" in res.failure_message()
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [rec["case_id"] for rec in records] == ["Q1", "Q2"]
    assert records[0]["passed"] and records[0]["model"] == "fake"
    assert records[0]["metrics"]["FactRecall"]["score"] == 1.0
    assert records[0]["tool_calls"][0][0]["name"] == "well_status"


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, question, user_id, thread_id=None):
        self.calls.append((question, user_id, thread_id))
        return Answer(answer=question, blocks=[], citations=[], tool_calls=[], model="m", error=None)


def test_multi_turn_threads():
    turn = lambda u, m, new=False: SimpleNamespace(user_id=u, message=m, new_thread=new)  # noqa: E731
    case = SimpleNamespace(id="Q11", question=None, user_id="U-201", turns=[
        turn("U-201", "a"), turn("U-201", "b"), turn("U-202", "c"),
        turn("U-201", "d"), turn("U-201", "e", new=True)])
    ask = Recorder()
    answers = run_case(case, ask, {})
    assert answers[-1].answer == "e"
    t = [c[2] for c in ask.calls]
    assert t[0] == t[1] == t[3]                # same user, same thread in this case
    assert t[2] not in (t[0], t[4])            # other user, own thread
    assert t[4] != t[0]                        # new_thread starts a fresh one


def test_follows_run_first_and_once():
    cases = [EvalCase(id="Q15", question="c", follows=["Q12", "Q13"]),
             EvalCase(id="Q12", question="a"),
             EvalCase(id="Q13", question="b", follows=["Q12"])]
    ask = Recorder()
    r = Runner(cases, ask)
    r.result("Q15")
    r.result("Q12")
    assert [c[0] for c in ask.calls] == ["a", "b", "c"]
    assert list(r.results) == ["Q12", "Q13", "Q15"]
    assert not r.results["Q12"].as_dependency and r.results["Q13"].as_dependency


def test_follows_cycle_is_an_error():
    r = Runner([EvalCase(id="A", question="a", follows=["B"]),
                EvalCase(id="B", question="b", follows=["A"])], Recorder())
    with pytest.raises(ValueError, match="cycle"):
        r.result("A")


def test_ask_error_fails_case():
    def boom(question, user_id, thread_id=None):
        raise RuntimeError("no model")
    res = Runner([EvalCase(id="Q1", question="q")], boom).result("Q1")
    assert not res.passed and "no model" in res.failure_message()


def test_isolated_db_uses_a_copy():
    real = get_settings().db_path
    before = os.environ.get("DB_PATH")
    with isolated_db() as copy:
        assert get_settings().db_path == copy != real
        assert copy.stat().st_size == real.stat().st_size
    assert os.environ.get("DB_PATH") == before
    assert get_settings().db_path == real
