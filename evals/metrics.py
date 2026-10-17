"""Eval metrics (deepeval). FactRecall and VisualMatch need no LLM; judge_metric() does.

The test case carries the answer in `actual_output` and the rest of the Answer in
`metadata`: {"citations": [...], "blocks": [...]}. Build it with `make_test_case()`.
"""

import json
import re

from deepeval.metrics import BaseMetric, GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

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


def make_test_case(input: str, answer: Answer) -> LLMTestCase:
    """deepeval test case for one scored answer."""
    return LLMTestCase(
        input=input,
        actual_output=answer.answer,
        metadata={"citations": answer.citations, "blocks": answer.blocks},
    )


def haystack(tc: LLMTestCase) -> str:
    """Normalised text to search: answer + citations + JSON of blocks."""
    meta = tc.metadata or {}
    parts = [tc.actual_output or "", *meta.get("citations", []),
             json.dumps(meta.get("blocks", []), ensure_ascii=False, default=str)]
    return normalise("\n".join(parts))


class FactRecall(BaseMetric):
    """Share of `must_include` items found. An item that is a list passes if any one of
    its alternatives is found. Any `must_not_include` match fails the case."""

    def __init__(self, must_include: list[str | list[str]], must_not_include: list[str] = ()):
        self.must_include = [[i] if isinstance(i, str) else list(i) for i in must_include]
        self.must_not_include = list(must_not_include)
        self.threshold = 1.0
        self.async_mode = False

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        text = haystack(test_case)
        missing = [alts for alts in self.must_include if not any(contains(text, a) for a in alts)]
        forbidden = [s for s in self.must_not_include if contains(text, s)]
        total = len(self.must_include)
        self.score = (total - len(missing)) / total if total else 1.0
        self.success = self.score >= self.threshold and not forbidden
        problems = []
        if missing:
            problems.append("missing: " + ", ".join(" | ".join(alts) for alts in missing))
        if forbidden:
            problems.append("forbidden found: " + ", ".join(forbidden))
        self.reason = "; ".join(problems) or f"all {total} found"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "FactRecall"


class VisualMatch(BaseMetric):
    """Some block has the expected visual type. No expected visual ("none"/None) passes."""

    def __init__(self, visual: str | None):
        self.visual = None if visual in (None, "none") else visual
        self.threshold = 1.0
        self.async_mode = False

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        types = [b.get("type") for b in (test_case.metadata or {}).get("blocks", [])]
        self.score = 1.0 if self.visual is None or self.visual in types else 0.0
        self.success = self.score >= self.threshold
        self.reason = f"expected {self.visual or 'any'}, got {types or 'no blocks'}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "VisualMatch"


def judge_metric(rubric: str) -> GEval:
    """LLM judge on the case rubric. Uses FALLBACK_MODEL on OpenRouter. Only with --judge."""
    from deepeval.models import OpenRouterModel

    from copilot.config import get_settings

    s = get_settings()
    return GEval(
        name="Judge",
        criteria=rubric,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=OpenRouterModel(model=s.fallback_model, api_key=s.openrouter_api_key),
        async_mode=False,
    )
