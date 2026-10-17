"""Eval result format, run log, report and HTML. Offline: ask() is evals.fake or a stub."""

import json
import os
import re
import subprocess
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from copilot import results
from copilot.api import Answer, ToolCall, build_answer
from copilot.config import ROOT
from copilot.llm import OpenRouterChat
from evals import fake, metrics, report, schema
from evals.cases import EvalCase, load_cases
from evals.runner import Runner
from evals.schema import Status


def rec(name, status, score=None, error=None, **details):
    return {"name": name, "status": status, "score": score, "error": error, "details": details}


def answer(text="", tool_calls=(), blocks=(), error=None, trace=None):
    return Answer(answer=text, blocks=list(blocks), citations=[], tool_calls=list(tool_calls),
                  model="stub", error=error, **({"trace": trace} if trace is not None else {}))


def run_one(case: EvalCase, ask, judge=False):
    return Runner([case], ask, judge=judge).result(case.id).record()


# ---------------------------------------------------------------------------
# Status rules
# ---------------------------------------------------------------------------

def test_error_has_priority_over_fail():
    assert schema.case_status(True, [rec("FactRecall", Status.FAIL, 0.0)]) == Status.ERROR
    assert schema.case_status(False, [rec("FactRecall", Status.FAIL, 0.0)]) == Status.FAIL
    assert schema.case_status(False, [rec("FactRecall", Status.PASS, 1.0),
                                      rec("Judge", Status.ERROR)]) == Status.PASS


def test_skip_and_error_not_in_score():
    ms = [rec("FactRecall", Status.FAIL, 0.5), rec("VisualMatch", Status.PASS, 1.0),
          rec("Judge", Status.SKIP), rec("X", Status.ERROR)]
    assert schema.case_score(ms) == 0.75
    assert schema.case_score([rec("Judge", Status.SKIP)]) is None


def test_visual_none_and_no_judge_are_skip():
    r = run_one(EvalCase(id="Q5", question="q", visual="none", must_include=["a"]),
                lambda q, u, t=None: answer("a"))
    by = {m["name"]: m for m in r["metrics"]}
    assert by["VisualMatch"]["status"] == Status.SKIP and by["VisualMatch"]["score"] is None
    assert by["Judge"]["status"] == Status.SKIP and by["Judge"]["reason"] == "no --judge"
    assert r["status"] == Status.PASS and r["score"] == 1.0


def test_metric_error_sets_incomplete(monkeypatch):
    class Boom(metrics.Skipped):
        def __init__(self):
            super().__init__("Judge", 1, "")
            self.skipped = False

        def measure(self, test_case, *a, **k):
            raise RuntimeError("judge API down")

    monkeypatch.setattr(metrics, "judge_metric", lambda rubric: Boom())
    r = run_one(EvalCase(id="Q1", question="q", must_include=["a"], rubric="r"),
                lambda q, u, t=None: answer("a"), judge=True)
    judge = next(m for m in r["metrics"] if m["name"] == "Judge")
    assert judge["status"] == Status.ERROR and "judge API down" in judge["error"]
    assert r["status"] == Status.PASS and r["incomplete"] is True and r["score"] == 1.0


def test_metric_record_fields():
    m = metrics.FactRecall(["WELL-0164", ["MNT-0172-028", "MNT 172"]], ["WELL-0001"])
    m.measure(metrics.make_test_case("q", answer("WELL-0164")))
    r = schema.metric_record(m)
    assert set(r) == {"name", "version", "status", "score", "threshold", "success", "reason", "error",
                      "evaluation_model", "details"}
    assert r["version"] == metrics.FactRecall.version and r["status"] == Status.FAIL
    assert r["details"]["found"] == ["WELL-0164"]
    assert r["details"]["missing"][0]["alternatives"] == ["MNT-0172-028", "MNT 172"]


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def test_generation_retrieval_and_no_visual():
    rid = results.put("well_status", [{"asset_id": "WELL-0164", "note": "MNT-0172-028"}])

    def ask(q, u, t=None):
        return answer("Only WELL-0170.", [ToolCall(name="well_status", args={}, result_id=rid)])

    r = run_one(EvalCase(id="Q2", question="q", visual="table",
                         must_include=["WELL-0170", "MNT-0172-028", "WELL-0999"]), ask)
    missing = {m["item"]: m for m in r["metrics"][0]["details"]["missing"]}
    assert missing["MNT-0172-028"]["in_tool_results"] and missing["MNT-0172-028"]["tools"] == ["well_status"]
    assert not missing["WELL-0999"]["in_tool_results"]
    assert r["status"] == Status.FAIL
    assert r["categories"] == ["retrieval", "generation", "no_visual"]


def test_wrong_visual_and_forbidden():
    r = run_one(EvalCase(id="Q2", question="q", visual="table", must_include=["a"],
                         must_not_include=["WELL-0001"]),
                lambda q, u, t=None: answer("a WELL-0001", blocks=[{"type": "bar_chart"}]))
    assert r["categories"] == ["forbidden", "wrong_visual"]


def test_rate_limit_error():
    r = run_one(EvalCase(id="Q3", question="q", must_include=["a"]),
                lambda q, u, t=None: answer(error="RateLimitError: Error code: 429"))
    assert r["status"] == Status.ERROR and r["categories"] == ["error", "rate_limit"]
    assert r["metrics"] == [] and r["score"] is None


def test_ask_raises_and_dependency_error():
    def ask(q, u, t=None):
        if q == "first":
            raise RuntimeError("boom")
        return answer("ok")
    r = Runner([EvalCase(id="Q12a", question="first"),
                EvalCase(id="Q12b", question="second", follows=["Q12a"])], ask)
    dep = r.result("Q12b")
    assert r.results["Q12a"].status == Status.ERROR and "boom" in r.results["Q12a"].error
    assert dep.status == Status.ERROR and "dependency Q12a errored" in dep.error
    assert r.results["Q12a"].as_dependency


# ---------------------------------------------------------------------------
# Offline run: log, report, history, baseline
# ---------------------------------------------------------------------------

@pytest.fixture
def offline_run(tmp_path):
    """A run of Q1–Q10 (A1) with evals.fake: Q1 PASS, Q10 ERROR, the rest FAIL."""
    cases = load_cases()
    selected = [c.id for c in cases if schema.group_of(c.id) == "A1"]
    log = tmp_path / "runs" / "20261017T000000Z-test.jsonl"
    r = Runner(cases, fake.ask, log_path=log, selected=selected)
    r.start(argv=["test"])
    for cid in selected:
        r.result(cid)
    r.finish()
    return log, selected


def lines(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_log_has_start_cases_end(offline_run):
    log, selected = offline_run
    recs = lines(log)
    assert recs[0]["type"] == "run_start" and recs[-1]["type"] == "run_end"
    start = recs[0]
    assert start["schema_version"] == 1 and start["run_id"] == log.stem
    assert start["cases"] == selected and start["today"] == "2026-10-16"
    assert {"sha", "branch", "dirty"} <= set(start["git"])
    assert start["db"]["counts"]["wells"] > 0 and start["users"]["U-201"]
    cases = [r for r in recs if r["type"] == "case"]
    assert [c["case_id"] for c in cases] == selected
    end = recs[-1]
    assert end["totals"] == {"PASS": 1, "FAIL": 8, "ERROR": 1}
    assert end["pass_rate"] == round(1 / 9, 4)
    assert end["by_group"]["A1"]["PASS"] == 1
    assert end["category_counts"]["rate_limit"] == 1
    q1 = cases[0]
    assert q1["status"] == "PASS" and q1["group"] == "A1" and q1["answers"][0]["trace"]
    call = q1["tool_calls"][0]
    assert call["name"] == "well_status" and call["row_count"] == 1 and call["rows_preview"]
    assert call["id"] == "fake-1"


def report_main(log, tmp_path, *args):
    return report.main([str(log), "--out-dir", str(tmp_path / "reports"),
                        "--history", str(tmp_path / "history.csv"),
                        "--baseline", str(tmp_path / "baseline.json"), *args])


def test_report_record_and_baseline(offline_run, tmp_path, capsys):
    log, _ = offline_run
    assert report_main(log, tmp_path, "--record", "--set-baseline") == 0
    out = capsys.readouterr().out
    assert "**1/10 pass · 8 fail · 1 error**" in out
    md = (tmp_path / "reports" / f"{log.stem}.md").read_text()
    assert "| Q1 | PASS | 1.00 | 1.00 PASS | 1.00 PASS | SKIP |" in md
    assert "| Q10 | ERROR |" in md and "## Failures" in md and "[retrieval]" in md
    assert "## Category counts" in md
    assert (tmp_path / "reports" / f"{log.stem}.html").exists()

    rows = (tmp_path / "history.csv").read_text().splitlines()
    assert rows[0].split(",") == report.HISTORY_COLUMNS and len(rows) == 2
    report_main(log, tmp_path, "--record")
    assert len((tmp_path / "history.csv").read_text().splitlines()) == 3

    base = json.loads((tmp_path / "baseline.json").read_text())
    assert base["run_id"] == log.stem and base["cases"]["Q1"] == {"status": "PASS", "score": 1.0}


def test_report_against_changed_baseline(offline_run, tmp_path):
    log, _ = offline_run
    run = report.load_run(log)
    base = report.baseline_from(run)
    base["cases"]["Q1"] = {"status": "FAIL", "score": 0.5}      # now PASS: a fix
    base["cases"]["Q2"] = {"status": "PASS", "score": 1.0}      # now FAIL: a regression
    base["cases"]["Q10"] = {"status": "PASS", "score": 1.0}     # now ERROR: a regression
    base["cases"]["Q3"]["score"] = 0.6                          # now 0.0: a score change
    base["metric_versions"]["FactRecall"] = 0
    (tmp_path / "baseline.json").write_text(json.dumps(base))

    ch = report.changes(run.cases, base)
    assert ch["regressions"] == [("Q2", "PASS", "FAIL"), ("Q10", "PASS", "ERROR")]
    assert ch["fixes"] == [("Q1", "FAIL", "PASS")]
    assert [c[0] for c in ch["score_changes"]] == ["Q1", "Q2", "Q3", ]

    report_main(log, tmp_path)
    md = (tmp_path / "reports" / f"{log.stem}.md").read_text()
    assert "- **regression** Q2: PASS → FAIL" in md and "- **regression** Q10: PASS → ERROR" in md
    assert "- fix Q1: FAIL → PASS" in md and "- score Q3: 0.60 → 0.00" in md
    assert "| FAIL → PASS |" in md and "2 regressions · 1 fixes" in md
    assert "metric versions differ from the baseline:** FactRecall v0 → v2" in md


def test_truncated_log_is_incomplete(offline_run, tmp_path):
    log, _ = offline_run
    cut = tmp_path / "cut.jsonl"
    cut.write_text("\n".join(log.read_text().splitlines()[:4]) + '\n{"type": "case", "case_')
    run = report.load_run(cut)
    assert not run.complete and len(run.cases) == 3
    md = report.render_markdown(run)
    assert "Incomplete run" in md and "1/3 pass · 2 fail · 0 error" in md
    assert "Incomplete run" in report.render_html(run)
    assert report_main(cut, tmp_path, "--record") == 1
    assert not (tmp_path / "history.csv").exists()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def test_html_self_contained_with_anchors_and_cards(offline_run):
    log, selected = offline_run
    page = report.render_html(report.load_run(log))
    assert not re.search(r"""(src|href|url)\s*[=(]\s*["']?https?://""", page, re.IGNORECASE)
    assert "http://" not in page and "https://" not in page
    for cid in selected:
        assert f'id="case-{cid}"' in page and f'href="#case-{cid}"' in page
    q2 = page[page.index('id="case-Q2"'):page.index('id="case-Q3"')]
    assert "WELL-0170" in q2 and "retrieval" in q2 and "generation" in q2
    assert "🔧 search_docs" in q2 and "1 of 1 rows" in q2
    q1 = page[page.index('id="case-Q1"'):page.index('id="case-Q2"')]
    assert "<mark>INS-0001-0203</mark>" in q1 and "Michael Turner" in q1
    assert "1200 in / 40 out tokens" in q1 and "📊 status_card" in q1
    assert 'data-filter="FAIL"' in page and 'data-filter="ERROR"' in page


def test_html_escapes_data(tmp_path):
    evil = "<script>alert('x')</script>"
    log = tmp_path / "run.jsonl"
    r = Runner([EvalCase(id="Q2", question=evil, must_include=["<b>"])],
               lambda q, u, t=None: answer(evil, trace=[{"kind": "user", "text": q},
                                                         {"kind": "ai", "text": evil}]),
               log_path=log)
    r.start(argv=[])
    r.result("Q2")
    r.finish()
    page = report.render_html(report.load_run(log))
    assert evil not in page and "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in page
    assert "✗ &lt;b&gt;" in page                 # the must_include item, escaped


# ---------------------------------------------------------------------------
# Answer.trace and reasoning capture
# ---------------------------------------------------------------------------

def test_answer_without_trace_validates():
    a = Answer(answer="x", blocks=[], citations=[], tool_calls=[], model="m", error=None)
    assert a.trace == []


def test_build_answer_trace():
    rid = results.put("well_status", [{"asset_id": "WELL-0001"}])
    turn = [
        HumanMessage("Is WELL-0001 producing?"),
        AIMessage("Let me check.", tool_calls=[{"name": "well_status", "args": {"asset_ids": ["WELL-0001"]},
                                                "id": "c1", "type": "tool_call"}],
                  additional_kwargs={"reasoning": "Need the status."},
                  usage_metadata={"input_tokens": 900, "output_tokens": 20, "total_tokens": 920},
                  response_metadata={"model_name": "gemma", "finish_reason": "tool_calls"}),
        ToolMessage('{"rows":[]}', tool_call_id="c1", name="well_status",
                    artifact={"result_id": rid, "ids": ["INS-1"], "notes": []}),
        AIMessage("No.", response_metadata={"model_name": "gemma", "finish_reason": "stop"}),
    ]
    a = build_answer(turn)
    assert [s["kind"] for s in a.trace] == ["user", "ai", "tool", "ai"]
    assert a.trace[0] == {"kind": "user", "text": "Is WELL-0001 producing?"}
    assert a.trace[1] == {"kind": "ai", "text": "Let me check.", "reasoning": "Need the status.",
                          "tool_calls": [{"id": "c1", "name": "well_status", "args": {"asset_ids": ["WELL-0001"]}}],
                          "model": "gemma", "usage": {"input_tokens": 900, "output_tokens": 20},
                          "finish_reason": "tool_calls"}
    assert a.trace[2] == {"kind": "tool", "tool_call_id": "c1", "name": "well_status",
                          "content": '{"rows":[]}', "status": "ok"}
    assert a.trace[3]["reasoning"] is None and a.trace[3]["usage"] is None
    assert a.answer == "No." and a.tool_calls[0].result_id == rid


def test_tool_error_step():
    turn = [HumanMessage("q"),
            AIMessage("", tool_calls=[{"name": "spills", "args": {}, "id": "c1", "type": "tool_call"}]),
            ToolMessage('{"error":"x"}', tool_call_id="c1", name="spills",
                        artifact={"result_id": None, "ids": [], "error": "x"})]
    assert build_answer(turn).trace[2]["status"] == "error"


def test_openrouter_reasoning_kept():
    llm = OpenRouterChat(model="m", api_key="k", base_url="http://localhost:1")
    raw = {"id": "g", "model": "m", "object": "chat.completion", "created": 0,
           "choices": [{"index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hi", "reasoning": "thinking"}}],
           "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    msg = llm._create_chat_result(raw).generations[0].message
    assert msg.additional_kwargs["reasoning"] == "thinking" and msg.content == "hi"


# ---------------------------------------------------------------------------
# pytest evals: summary
# ---------------------------------------------------------------------------

def test_pytest_evals_summary():
    env = {**os.environ, "EVAL_ASK": "evals.fake:ask"}
    p = subprocess.run([sys.executable, "-m", "pytest", "evals", "--cases", "Q1,Q2,Q10", "-q",
                        "-p", "no:cacheprovider"], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=120)
    out = p.stdout
    assert p.returncode == 1                       # FAIL and ERROR make the run red
    assert "| Q1 | PASS |" in out and "| Q2 | FAIL |" in out and "| Q10 | ERROR |" in out
    assert "1/3 pass · 1 fail · 1 error" in out
    assert "run log:" in out and "uv run python -m evals.report --record" in out
    assert "ERROR: Q10 · ERROR" in out


def test_chains_group_by_follows_and_keep_order():
    from evals.cases import load_cases
    from evals.runner import Runner

    r = Runner(load_cases(), ask=None)
    chains = r.chains(["Q1", "Q12b", "Q15a", "Q14b", "Q2"])
    assert ["Q1"] in chains and ["Q2"] in chains and ["Q14a", "Q14b"] in chains
    q12 = next(c for c in chains if "Q12b" in c)
    assert q12[0] == "Q12a" and set(q12) == {"Q12a", "Q12b", "Q15a"}


def test_run_all_parallel_matches_serial():
    from evals.cases import load_cases
    from evals.fake import ask
    from evals.runner import Runner

    cases = load_cases()
    ids = [c.id for c in cases]
    serial, parallel = Runner(cases, ask, selected=ids), Runner(cases, ask, selected=ids)
    serial.run_all(workers=1)
    parallel.run_all(workers=6)
    assert {k: v.status for k, v in serial.results.items()} == \
           {k: v.status for k, v in parallel.results.items()}
    assert not any(v.as_dependency for v in parallel.results.values())
