"""pytest wiring for the evals: options, the session runner, the summary table."""

import os

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")

from evals.cases import load_cases  # noqa: E402
from evals.runner import Runner, get_ask, isolated_db, new_log_path  # noqa: E402

# --cases <group>: named groups of case IDs. Anything else is a comma-separated ID list.
GROUPS = {
    "A1": [f"Q{i}" for i in range(1, 11)],
    "A2": [f"Q{i}" for i in range(11, 19)],
}

_runner = pytest.StashKey[Runner]()


def pytest_addoption(parser):
    group = parser.getgroup("evals")
    group.addoption("--judge", action="store_true",
                    help="also score each case's rubric with the GEval LLM judge (OpenRouter)")
    group.addoption("--cases", default=None,
                    help=f"only these cases: a group ({', '.join(GROUPS)}) or IDs, e.g. Q1,Q3")


def selected_cases(option: str | None):
    cases = load_cases()
    if not option:
        return cases
    wanted = set(GROUPS.get(option, [])) or {s.strip() for s in option.split(",")}
    return [c for c in cases if c.id in wanted]


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = selected_cases(metafunc.config.getoption("cases"))
        metafunc.parametrize("case", cases, ids=[c.id for c in cases])


@pytest.fixture(scope="session")
def runner(request):
    """One runner per session, on a temp copy of the database."""
    with isolated_db():
        r = Runner(load_cases(), get_ask(), judge=request.config.getoption("judge"),
                   log_path=new_log_path())
        request.config.stash[_runner] = r
        yield r


def _cell(m) -> str:
    if m is None:
        return "-"
    return f"{m.score:.2f} {'pass' if m.is_successful() else 'FAIL'}"


def pytest_terminal_summary(terminalreporter, config):
    r = config.stash.get(_runner, None)
    if r is None or not r.results:
        return
    header = ("case", "FactRecall", "VisualMatch", "Judge", "seconds")
    rows = []
    for res in r.results.values():
        name = res.case.id + (" (dep)" if res.as_dependency else "")
        if res.error:
            rows.append((name, "ERROR", "ERROR", "-", f"{res.seconds:.1f}"))
        else:
            rows.append((name, _cell(res.metric("FactRecall")), _cell(res.metric("VisualMatch")),
                         _cell(res.metric("Judge")), f"{res.seconds:.1f}"))
    widths = [max(len(str(row[i])) for row in [header, *rows]) for i in range(len(header))]
    tr = terminalreporter
    tr.section("eval summary")
    for row in [header, tuple("-" * w for w in widths), *rows]:
        tr.write_line("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    scored = [res for res in r.results.values() if not res.as_dependency]
    tr.write_line(f"\ncases passed: {sum(res.passed for res in scored)} / {len(scored)}")
    if r.log_path:
        tr.write_line(f"run log: {r.log_path}")
