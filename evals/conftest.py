"""pytest wiring for the evals: options, the session runner, the summary table and HTML report."""

import os

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")

from copilot.config import get_settings  # noqa: E402
from evals import report  # noqa: E402
from evals.cases import load_cases  # noqa: E402
from evals.runner import (WORKERS, Runner, db_snapshot, get_ask, git_info, isolated_db,  # noqa: E402
                          new_log_path, new_run_id)
from evals.schema import group_of, pass_line  # noqa: E402

_runner = pytest.StashKey[Runner]()
_html = pytest.StashKey[object]()


def pytest_addoption(parser):
    group = parser.getgroup("evals")
    group.addoption("--judge", action="store_true",
                    help="also run the LLM judge (JUDGE_MODEL on OpenRouter)")
    group.addoption("--cases", default=None,
                    help="only these cases: a group (A1 = Q1–Q10, A2 = Q11–Q18) or IDs, e.g. Q1,Q3")
    group.addoption("--workers", type=int, default=int(os.getenv("EVAL_WORKERS", WORKERS)),
                    help=f"stateless cases run in parallel (default {WORKERS}, env EVAL_WORKERS; "
                         f"1 = one at a time); stateful chains always run one at a time")


def selected_cases(option: str | None):
    cases = load_cases()
    if not option:
        return cases
    if option in ("A1", "A2"):
        return [c for c in cases if group_of(c.id) == option]
    wanted = {s.strip() for s in option.split(",")}
    return [c for c in cases if c.id in wanted]


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = selected_cases(metafunc.config.getoption("cases"))
        metafunc.parametrize("case", cases, ids=[c.id for c in cases])


@pytest.fixture(scope="session")
def runner(request):
    """One runner per session, on a temp copy of the database. Writes run_start and run_end.
    Runs every selected case up front (stateless cases in parallel, then the stateful chains one
    at a time, each on the snapshot taken here); the tests then read the cached results."""
    source_db = get_settings().db_path
    selected = [c.id for c in selected_cases(request.config.getoption("cases"))]
    with isolated_db() as db_path, db_snapshot(db_path) as reset:
        r = Runner(load_cases(), get_ask(), judge=request.config.getoption("judge"),
                   log_path=new_log_path(new_run_id(git_info()["sha"])), selected=selected)
        r.start(argv=list(request.config.invocation_params.args), db_path=source_db)
        r.run_all(selected, workers=request.config.getoption("workers"), reset=reset)
        request.config.stash[_runner] = r
        yield r
        r.finish()


def pytest_terminal_summary(terminalreporter, config):
    r = config.stash.get(_runner, None)
    if r is None or not r.results:
        return
    tr = terminalreporter
    tr.section("eval summary")
    baseline = report.load_baseline()
    run = report.load_run(r.log_path) if r.log_path and r.log_path.exists() else None
    cases = run.cases if run else [res.record() for res in r.results.values()]
    for line in report.table(cases, baseline).splitlines():
        tr.write_line(line)
    summary = run.summary if run else None
    if summary:
        rate = "-" if summary["pass_rate"] is None else f"{summary['pass_rate']:.2f}"
        tr.write_line(f"\n{pass_line(summary['totals'])} · pass rate {rate}")
        if line := report.baseline_line(run, baseline):
            tr.write_line(line)
    if run:
        tr.write_line(f"run log: {r.log_path}")
        tr.write_line(f"html:    {report.write_html(run, baseline)}")
    tr.write_line("report:  uv run python -m evals.report --record")
