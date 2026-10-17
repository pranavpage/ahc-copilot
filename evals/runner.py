"""Runs eval cases through ask(): threads, dependencies, metrics, DB isolation, run log.

The run log (`evals/runs/<run_id>.jsonl`) has one `run_start` line, one `case` line per case
(written as soon as the case is scored) and one `run_end` line. Format: evals/schema.py, EVALS.md.
"""

import importlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterator

from deepeval.metrics import BaseMetric

from copilot import results
from copilot.api import Answer
from copilot.config import ROOT, get_settings
from evals import schema
from evals.cases import EvalCase
from evals.metrics import METRIC_VERSIONS, build_metrics, judge_model, make_test_case
from evals.schema import Status

Ask = Callable[..., Answer]
RUNS_DIR = Path(__file__).resolve().parent / "runs"
ROWS_PREVIEW = 20          # rows of each tool result kept in the run log
WORKERS = 6                # cases (dependency chains) run at the same time; --workers / EVAL_WORKERS


def get_ask() -> Ask:
    """The ask() under test, from env EVAL_ASK ("module:function", default copilot.api:ask)."""
    module, _, name = os.getenv("EVAL_ASK", "copilot.api:ask").partition(":")
    return getattr(importlib.import_module(module), name or "ask")


def turns(case: EvalCase) -> list[tuple[str, str, bool]]:
    """(user_id, message, new_thread) for each turn. A single question is one turn."""
    if case.question is not None:
        return [(case.user_id, case.question, False)]
    return [(t.user_id, t.message, getattr(t, "new_thread", False)) for t in case.turns]


def iter_answers(case: EvalCase, ask: Ask, threads: dict[tuple[str, str], str]) -> Iterator[Answer]:
    """Ask each turn in order and yield each answer. The last one is scored.

    `threads` maps (case_id, user_id) to that user's current thread in this case. A turn
    with new_thread starts a fresh one; a user's first turn in the case always does.
    """
    for user_id, message, new_thread in turns(case):
        key = (case.id, user_id)
        if new_thread or key not in threads:
            threads[key] = f"eval-{case.id}-{user_id}-{uuid.uuid4().hex[:8]}"
        yield ask(message, user_id, threads[key])


def run_case(case: EvalCase, ask: Ask, threads: dict[tuple[str, str], str]) -> list[Answer]:
    """All answers of the case, in order."""
    return list(iter_answers(case, ask, threads))


def judge_input(case: EvalCase, answers: list[Answer]) -> str:
    """What the judge sees as input: the question, or the conversation up to the last turn."""
    ts = turns(case)
    if len(ts) == 1:
        return ts[0][1]
    lines = []
    for i, ((user_id, message, _), answer) in enumerate(zip(ts, answers)):
        lines.append(f"{user_id}: {message}")
        if i < len(answers) - 1:
            lines.append(f"copilot: {answer.answer}")
    return "\n".join(lines)


def tool_log(answers: list[Answer]) -> list[dict]:
    """Every tool call of every turn, with the first ROWS_PREVIEW rows of its result.

    `id` is the tool call id from the trace (matched by order), so a trace `tool` step can
    be joined to its rows.
    """
    out = []
    for turn, answer in enumerate(answers):
        ids = [c["id"] for step in answer.trace if step.get("kind") == "ai"
               for c in step.get("tool_calls", [])]
        if len(ids) != len(answer.tool_calls):
            ids = [None] * len(answer.tool_calls)
        for call_id, call in zip(ids, answer.tool_calls):
            try:
                rows = results.get(call.result_id) if call.result_id else None
            except KeyError:
                rows = None
            out.append({"turn": turn, "id": call_id, "name": call.name, "args": call.args,
                        "result_id": call.result_id, "row_count": None if rows is None else len(rows),
                        "rows_preview": None if rows is None else rows[:ROWS_PREVIEW]})
    return out


@dataclass
class CaseResult:
    case: EvalCase
    answers: list[Answer] = field(default_factory=list)
    metrics: list[BaseMetric] = field(default_factory=list)
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)   # ask() traceback, Answer.error, dependency
    as_dependency: bool = False     # ran only because another case follows it
    tools: list[dict] = field(default_factory=list)   # tool_log(), taken right after the run

    @property
    def error(self) -> str | None:
        return "\n".join(self.errors) or None

    @property
    def metric_records(self) -> list[dict]:
        return [schema.metric_record(m) for m in self.metrics]

    @property
    def status(self) -> Status:
        return schema.case_status(bool(self.errors), self.metric_records)

    @property
    def passed(self) -> bool:
        return self.status == Status.PASS

    def metric(self, name: str) -> BaseMetric | None:
        return next((m for m in self.metrics if m.__name__.startswith(name)), None)

    def record(self) -> dict:
        """The `case` line of the run log."""
        metrics, status = self.metric_records, self.status
        key = "question" if self.case.question is not None else "turns"
        last = self.answers[-1] if self.answers else None
        return {
            "type": "case",
            "case_id": self.case.id,
            "group": schema.group_of(self.case.id),
            "status": status,
            "score": schema.case_score(metrics),
            "incomplete": schema.incomplete(status, metrics),
            "categories": schema.categories(status, self.errors, metrics),
            "metrics": metrics,
            key: self.case.question if key == "question" else
                 [t.model_dump() for t in self.case.turns],
            "user_id": self.case.user_id,
            "expected": {"visual": self.case.visual, "must_include": self.case.must_include,
                         "must_not_include": self.case.must_not_include, "rubric": self.case.rubric,
                         "follows": self.case.follows},
            "answers": [a.model_dump(exclude={"tool_calls"}) for a in self.answers],
            "tool_calls": self.tools,
            "error": self.error,
            "errors": self.errors,
            "seconds": round(self.seconds, 2),
            "model": last.model if last else None,
            "as_dependency": self.as_dependency,
        }

    def failure_message(self) -> str:
        from evals.report import failure_block

        return failure_block(self.record())


def git_info() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    try:
        return {"sha": git("rev-parse", "--short", "HEAD") or None,
                "branch": git("rev-parse", "--abbrev-ref", "HEAD") or None,
                "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.SubprocessError):
        return {"sha": None, "branch": None, "dirty": None}


def new_run_id(sha: str | None = None) -> str:
    """<UTC yyyymmddThhmmssZ>-<git short sha>"""
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{sha or 'nogit'}"


def new_log_path(run_id: str | None = None) -> Path:
    """evals/runs/<run_id>.jsonl"""
    return RUNS_DIR / f"{run_id or new_run_id(git_info()['sha'])}.jsonl"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_info() -> dict:
    """today, the latest load run and the users, from the database under test."""
    from copilot import db

    try:
        load = db.rows("SELECT run_id, loaded_at, data_dir, counts FROM load_runs "
                       "ORDER BY run_id DESC LIMIT 1")
        users = {r["user_id"]: r["name"] for r in db.rows("SELECT user_id, name FROM users")}
        today = db.today()
    except sqlite3.Error as e:
        return {"today": None, "db": {"path": str(get_settings().db_path), "error": str(e)}, "users": {}}
    load = load[0] if load else {}
    return {"today": today,
            "db": {"path": str(get_settings().db_path),
                   "load_run": {k: load[k] for k in ("run_id", "loaded_at", "data_dir")} if load else None,
                   "counts": json.loads(load["counts"]) if load else None},
            "users": users}


class Runner:
    """Runs each case at most once per session, after the cases it follows.

    `selected`: the case IDs asked for. A selected case is never marked as a dependency, even
    when another case runs it first. `run_all` runs independent chains of cases in parallel.
    """

    def __init__(self, cases: list[EvalCase], ask: Ask, judge: bool = False,
                 log_path: Path | None = None, selected: list[str] | None = None):
        self.cases = {c.id: c for c in cases}
        self.ask = ask
        self.judge = judge
        self.log_path = log_path
        self.selected = set(selected) if selected is not None else None
        self.threads: dict[tuple[str, str], str] = {}
        self.results: dict[str, CaseResult] = {}    # in finish order
        self._local = threading.local()             # per thread: the cases being resolved
        self._lock = threading.Lock()               # results and the run log
        self.run_id = log_path.stem if log_path else None
        self._started = time.perf_counter()

    # -- run log -------------------------------------------------------------

    def start(self, argv: list[str] | None = None, db_path: Path | None = None) -> dict:
        """Write the run_start line. `db_path`: the database the run was copied from."""
        s = get_settings()
        gi = git_info()
        rec = {
            "type": "run_start", "schema_version": schema.SCHEMA_VERSION, "run_id": self.run_id,
            "started_at": _now(), "git": gi,
            "ask": os.getenv("EVAL_ASK", "copilot.api:ask"),
            "model": s.model, "fallback_model": s.fallback_model,
            "judge": self.judge, "judge_model": judge_model() if self.judge else None,
            "metric_versions": METRIC_VERSIONS,
            **db_info(),
            "cases": sorted(self.selected or self.cases, key=schema.case_order),
            "argv": list(sys.argv if argv is None else argv),
        }
        if db_path is not None:
            rec["db"]["path"] = str(db_path)
        self._started = time.perf_counter()
        self._write(rec)
        return rec

    def finish(self) -> dict:
        """Write the run_end line."""
        summary = schema.summarize([r.record() for r in self.results.values()])
        rec = {"type": "run_end", "finished_at": _now(),
               "seconds": round(time.perf_counter() - self._started, 2), **summary}
        self._write(rec)
        return rec

    def _write(self, rec: dict) -> None:
        if self.log_path is None:
            return
        line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as f:
                f.write(line)

    # -- cases ---------------------------------------------------------------

    def chains(self, case_ids: list[str]) -> list[list[str]]:
        """The cases and everything they follow, split into groups linked by `follows`, each
        in a safe run order (a case after the cases it follows). Groups can run in parallel."""
        parent: dict[str, str] = {}

        def find(c: str) -> str:
            while parent.setdefault(c, c) != c:
                c = parent[c]
            return c

        todo, seen = list(case_ids), set()
        while todo:
            c = todo.pop()
            if c in seen or c not in self.cases:
                continue
            seen.add(c)
            for dep in self.cases[c].follows:
                parent[find(dep)] = find(c)
                todo.append(dep)
            find(c)
        groups: dict[str, list[str]] = {}
        for c in sorted(seen, key=schema.case_order):
            groups.setdefault(find(c), []).append(c)
        return sorted(groups.values(), key=lambda g: schema.case_order(g[0]))

    def run_all(self, case_ids: list[str] | None = None, workers: int = WORKERS) -> None:
        """Run the cases, `workers` chains at a time. Within a chain, cases run one by one
        (`result` runs what a case follows first). Results stay cached for `result`."""
        ids = list(case_ids if case_ids is not None else self.selected or self.cases)

        def run_chain(chain: list[str]) -> None:
            for c in chain:
                self.result(c, as_dependency=c not in ids)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for future in [pool.submit(run_chain, ch) for ch in self.chains(ids)]:
                future.result()

    def result(self, case_id: str, as_dependency: bool = False) -> CaseResult:
        if self.selected is not None and case_id in self.selected:
            as_dependency = False
        if case_id in self.results:
            if not as_dependency:
                self.results[case_id].as_dependency = False
            return self.results[case_id]
        running = self._local.__dict__.setdefault("running", [])
        if case_id in running:
            raise ValueError(f"follows cycle: {' -> '.join(running + [case_id])}")
        if case_id not in self.cases:
            raise ValueError(f"unknown case {case_id!r} in follows")
        case = self.cases[case_id]
        running.append(case_id)
        try:
            deps = [self.result(dep, as_dependency=True) for dep in case.follows]
        finally:
            running.pop()
        res = self._run(case)
        res.errors += [f"dependency {d.case.id} errored" for d in deps if d.status == Status.ERROR]
        res.as_dependency = as_dependency
        with self._lock:
            self.results[case_id] = res
        self._write(res.record())
        return res

    def _run(self, case: EvalCase) -> CaseResult:
        res = CaseResult(case)
        start = time.perf_counter()
        try:
            for answer in iter_answers(case, self.ask, self.threads):
                res.answers.append(answer)
        except Exception:
            res.errors.append(f"ask() raised:\n{traceback.format_exc()}")
        res.seconds = time.perf_counter() - start
        res.errors += [f"Answer.error (turn {i + 1}): {a.error}" for i, a in enumerate(res.answers)
                       if a.error]
        res.tools = tool_log(res.answers)
        last = res.answers[-1] if res.answers else None
        if last is not None and last.error is None and len(res.answers) == len(turns(case)):
            tc = make_test_case(judge_input(case, res.answers), last)
            res.metrics = build_metrics(case, self.judge)
            for m in res.metrics:
                try:
                    m.measure(tc)
                except Exception as e:      # a judge error is a metric ERROR, not a case ERROR
                    m.error, m.success, m.reason = f"{type(e).__name__}: {e}", False, f"error: {e}"
        return res


@contextmanager
def isolated_db():
    """Point DB_PATH at a temp copy of the database, so eval writes never reach the real one."""
    src = get_settings().db_path
    if not src.exists():
        raise FileNotFoundError(f"{src} not found. Build it: uv sync && uv run python db/load.py")
    old = os.environ.get("DB_PATH")
    with tempfile.TemporaryDirectory(prefix="copilot-eval-") as tmp:
        dst = Path(tmp) / src.name
        with closing(sqlite3.connect(f"file:{src}?mode=ro", uri=True)) as a, \
             closing(sqlite3.connect(dst)) as b:
            a.backup(b)
        os.environ["DB_PATH"] = str(dst)
        get_settings.cache_clear()
        try:
            yield dst
        finally:
            if old is None:
                os.environ.pop("DB_PATH", None)
            else:
                os.environ["DB_PATH"] = old
            get_settings.cache_clear()
