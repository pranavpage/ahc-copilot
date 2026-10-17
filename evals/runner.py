"""Runs eval cases through ask(): threads, dependencies, metrics, DB isolation, run log."""

import importlib
import json
import os
import sqlite3
import tempfile
import time
import traceback
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from deepeval.metrics import BaseMetric

from copilot.api import Answer
from copilot.config import get_settings
from evals.cases import EvalCase
from evals.metrics import FactRecall, VisualMatch, judge_metric, make_test_case

Ask = Callable[..., Answer]
RUNS_DIR = Path(__file__).resolve().parent / "runs"


def get_ask() -> Ask:
    """The ask() under test, from env EVAL_ASK ("module:function", default copilot.api:ask)."""
    module, _, name = os.getenv("EVAL_ASK", "copilot.api:ask").partition(":")
    return getattr(importlib.import_module(module), name or "ask")


def turns(case: EvalCase) -> list[tuple[str, str, bool]]:
    """(user_id, message, new_thread) for each turn. A single question is one turn."""
    if case.question is not None:
        return [(case.user_id, case.question, False)]
    return [(t.user_id, t.message, getattr(t, "new_thread", False)) for t in case.turns]


def run_case(case: EvalCase, ask: Ask, threads: dict[tuple[str, str], str]) -> list[Answer]:
    """Ask each turn in order and return all answers. The last one is scored.

    `threads` maps (case_id, user_id) to that user's current thread in this case. A turn
    with new_thread starts a fresh one; a user's first turn in the case always does.
    """
    answers = []
    for user_id, message, new_thread in turns(case):
        key = (case.id, user_id)
        if new_thread or key not in threads:
            threads[key] = f"eval-{case.id}-{user_id}-{uuid.uuid4().hex[:8]}"
        answers.append(ask(message, user_id, threads[key]))
    return answers


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


@dataclass
class CaseResult:
    case: EvalCase
    answers: list[Answer] = field(default_factory=list)
    metrics: list[BaseMetric] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None        # exception from ask(), with traceback
    as_dependency: bool = False     # ran only because another case follows it

    @property
    def passed(self) -> bool:
        return self.error is None and all(m.is_successful() for m in self.metrics)

    def metric(self, name: str) -> BaseMetric | None:
        return next((m for m in self.metrics if m.__name__.startswith(name)), None)

    def failure_message(self) -> str:
        lines = [f"{self.case.id} failed"]
        if self.error:
            lines.append(f"  ask() raised:\n{self.error}")
        for m in self.metrics:
            if not m.is_successful():
                lines.append(f"  {m.__name__}: score {m.score:.2f}: {m.reason}")
        if self.answers:
            last = self.answers[-1]
            if last.error:
                lines.append(f"  Answer.error: {last.error}")
            lines.append(f"  answer: {last.answer[:500]}")
        return "\n".join(lines)

    def log_record(self) -> dict:
        last = self.answers[-1] if self.answers else None
        key = "question" if self.case.question is not None else "turns"
        return {
            "case_id": self.case.id,
            key: self.case.question if key == "question" else
                 [t.model_dump() for t in self.case.turns],
            "answers": [a.model_dump(exclude={"tool_calls"}) for a in self.answers],
            "tool_calls": [[c.model_dump() for c in a.tool_calls] for a in self.answers],
            "metrics": {m.__name__: {"score": m.score, "passed": m.is_successful(),
                                     "reason": m.reason} for m in self.metrics},
            "passed": self.passed,
            "error": self.error,
            "seconds": round(self.seconds, 2),
            "model": last.model if last else None,
            "as_dependency": self.as_dependency,
        }


class Runner:
    """Runs each case at most once per session, after the cases it follows."""

    def __init__(self, cases: list[EvalCase], ask: Ask, judge: bool = False,
                 log_path: Path | None = None):
        self.cases = {c.id: c for c in cases}
        self.ask = ask
        self.judge = judge
        self.log_path = log_path
        self.threads: dict[tuple[str, str], str] = {}
        self.results: dict[str, CaseResult] = {}    # in run order
        self._running: list[str] = []

    def result(self, case_id: str, as_dependency: bool = False) -> CaseResult:
        if case_id in self.results:
            if not as_dependency:
                self.results[case_id].as_dependency = False
            return self.results[case_id]
        if case_id in self._running:
            raise ValueError(f"follows cycle: {' -> '.join(self._running + [case_id])}")
        if case_id not in self.cases:
            raise ValueError(f"unknown case {case_id!r} in follows")
        case = self.cases[case_id]
        self._running.append(case_id)
        try:
            for dep in case.follows:
                self.result(dep, as_dependency=True)
        finally:
            self._running.pop()
        res = self._run(case)
        res.as_dependency = as_dependency
        self.results[case_id] = res
        self._log(res)
        return res

    def _run(self, case: EvalCase) -> CaseResult:
        res = CaseResult(case)
        start = time.perf_counter()
        try:
            res.answers = run_case(case, self.ask, self.threads)
        except Exception:
            res.error = traceback.format_exc()
        res.seconds = time.perf_counter() - start
        if res.answers:
            tc = make_test_case(judge_input(case, res.answers), res.answers[-1])
            res.metrics = [FactRecall(case.must_include, case.must_not_include),
                           VisualMatch(case.visual)]
            if self.judge and case.rubric:
                res.metrics.append(judge_metric(case.rubric))
            for m in res.metrics:
                try:
                    m.measure(tc)
                except Exception as e:      # a judge error fails the case, not the session
                    m.error, m.score, m.success, m.reason = str(e), 0.0, False, f"error: {e}"
        return res

    def _log(self, res: CaseResult) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps(res.log_record(), ensure_ascii=False, default=str) + "\n")


def new_log_path() -> Path:
    """evals/runs/<UTC timestamp>.jsonl"""
    return RUNS_DIR / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"


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
