"""Eval metrics (deepeval). FactRecall and VisualMatch need no LLM; the Judge does.

The test case carries the answer in `actual_output` and the rest of the Answer in
`metadata`: {"citations": [...], "blocks": [...], "tool_results": [{"name", "text"}]}.
Build it with `make_test_case()`.

Each metric has a `version` (bump it when its logic changes) and `details` (a dict for the
report). Add a new metric to METRICS; the runner builds one of each per case.
"""

import json
import re

from deepeval.metrics import BaseMetric, GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from copilot import results
from copilot.api import Answer

# A comma between digits that is followed by exactly 3 digits: "5,000" -> "5000".
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def normalise(text: str) -> str:
    """Lowercase, drop thousands separators, unicode minus -> '-'."""
    return _THOUSANDS.sub("", text.lower().replace("−", "-"))


def contains(haystack: str, needle: str) -> bool:
    """`needle` in the normalised `haystack`, not as part of a longer word or number.

    "3.2" does not match "13.2" or "3.25", and "21" does not match "2021".
    """
    needle = normalise(needle)
    left = r"(?<![\w.])" if needle[:1].isalnum() else ""
    right = r"(?!\w|\.\d)" if needle[-1:].isalnum() else ""
    return re.search(left + re.escape(needle) + right, haystack) is not None


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def tool_results(answer: Answer) -> list[dict]:
    """[{name, text}] for each data tool call of the answer: the normalised JSON of its rows,
    from the result store."""
    out = []
    for call in answer.tool_calls:
        try:
            rows = results.get(call.result_id) if call.result_id else None
        except KeyError:
            rows = None
        if rows is not None:
            out.append({"name": call.name, "text": normalise(_dumps(rows))})
    return out


def make_test_case(input: str, answer: Answer) -> LLMTestCase:
    """deepeval test case for one scored answer."""
    return LLMTestCase(
        input=input,
        actual_output=answer.answer,
        metadata={"citations": answer.citations, "blocks": answer.blocks,
                  "tool_results": tool_results(answer)},
    )


def haystack(tc: LLMTestCase) -> str:
    """Normalised text to search: answer + citations + JSON of blocks."""
    meta = tc.metadata or {}
    parts = [tc.actual_output or "", *meta.get("citations", []), _dumps(meta.get("blocks", []))]
    return normalise("\n".join(parts))


class _Sync:
    """Synchronous custom metric."""

    async_mode = False

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)


class FactRecall(_Sync, BaseMetric):
    """Share of `must_include` items found. An item that is a list passes if any one of
    its alternatives is found. Any `must_not_include` match fails the case.

    details: found, missing [{item, alternatives, in_tool_results, tools}], forbidden.
    `in_tool_results`: some alternative is in the rows of a tool call of the scored turn.
    """

    version = 1

    def __init__(self, must_include: list[str | list[str]], must_not_include: list[str] = ()):
        self.must_include = [[i] if isinstance(i, str) else list(i) for i in must_include]
        self.must_not_include = list(must_not_include)
        self.threshold = 1.0
        self.details = {}

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        text = haystack(test_case)
        tools = (test_case.metadata or {}).get("tool_results", [])
        found, missing = [], []
        for alts in self.must_include:
            hit = next((a for a in alts if contains(text, a)), None)
            if hit is not None:
                found.append(hit)
                continue
            in_tools = [t["name"] for t in tools if any(contains(t["text"], a) for a in alts)]
            missing.append({"item": alts[0], "alternatives": alts, "in_tool_results": bool(in_tools),
                            "tools": list(dict.fromkeys(in_tools))})
        forbidden = [s for s in self.must_not_include if contains(text, s)]
        total = len(self.must_include)
        self.score = (total - len(missing)) / total if total else 1.0
        self.success = self.score >= self.threshold and not forbidden
        self.details = {"found": found, "missing": missing, "forbidden": forbidden}
        problems = []
        if missing:
            problems.append("missing: " + ", ".join(" | ".join(m["alternatives"]) for m in missing))
        if forbidden:
            problems.append("forbidden found: " + ", ".join(forbidden))
        self.reason = "; ".join(problems) or f"all {total} found"
        return self.score

    @property
    def __name__(self):
        return "FactRecall"


class VisualMatch(_Sync, BaseMetric):
    """Some block has the expected visual type. SKIP when no visual is expected ("none"/None).

    details: expected, actual (the block types).
    """

    version = 1

    def __init__(self, visual: str | None):
        self.visual = None if visual in (None, "none") else visual
        self.threshold = 1.0
        self.details = {}

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        types = [b.get("type") for b in (test_case.metadata or {}).get("blocks", [])]
        self.details = {"expected": self.visual, "actual": types}
        if self.visual is None:
            self.skipped, self.success, self.score = True, True, None
            self.reason = f"no visual expected, got {types or 'no blocks'}"
            return 1.0
        self.score = 1.0 if self.visual in types else 0.0
        self.success = self.score >= self.threshold
        self.reason = f"expected {self.visual}, got {types or 'no blocks'}"
        return self.score

    @property
    def __name__(self):
        return "VisualMatch"


class Judge(GEval):
    """LLM judge on the case rubric (GEval). Uses FALLBACK_MODEL on OpenRouter. Only with --judge.

    details: rubric, evaluation_model.
    """

    version = 1

    def __init__(self, rubric: str, model=None):
        if model is None:
            from deepeval.models import OpenRouterModel

            from copilot.config import get_settings

            s = get_settings()
            model = OpenRouterModel(model=s.fallback_model, api_key=s.openrouter_api_key)
        super().__init__(name="Judge", criteria=rubric, model=model, async_mode=False,
                         evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT])
        self.rubric = rubric

    @property
    def details(self) -> dict:
        return {"rubric": self.rubric, "evaluation_model": self.evaluation_model}

    @property
    def __name__(self):
        return "Judge"


class Skipped(_Sync, BaseMetric):
    """Placeholder for a metric that does not apply to a case (status SKIP)."""

    def __init__(self, name: str, version: int | None, reason: str):
        self.name, self.version, self.reason = name, version, reason
        self.skipped, self.success, self.threshold, self.details = True, True, None, {}

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return 1.0

    @property
    def __name__(self):
        return self.name


def judge_metric(rubric: str) -> GEval:
    """The Judge for one rubric."""
    return Judge(rubric)


def build_metrics(case, judge: bool) -> list[BaseMetric]:
    """One of each metric in METRICS for this case."""
    return [make(case, judge) for make in METRICS]


def _judge(case, judge: bool) -> BaseMetric:
    if not judge:
        return Skipped("Judge", Judge.version, "no --judge")
    if not case.rubric:
        return Skipped("Judge", Judge.version, "no rubric")
    return judge_metric(case.rubric)


# (case, judge flag) -> metric. Order = the columns of the report.
METRICS = [
    lambda case, judge: FactRecall(case.must_include, case.must_not_include),
    lambda case, judge: VisualMatch(case.visual),
    _judge,
]

METRIC_VERSIONS = {"FactRecall": FactRecall.version, "VisualMatch": VisualMatch.version,
                   "Judge": Judge.version}
