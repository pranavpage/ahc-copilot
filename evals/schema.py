"""The one result format for evals: statuses, metric and case records, failure categories, totals.

The runner writes these records to the run log; the pytest summary and `evals.report` read them.
The rules are written out in EVALS.md.
"""

import re
from collections import Counter
from enum import StrEnum

SCHEMA_VERSION = 1


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"


METRIC_NAMES = ("FactRecall", "VisualMatch", "Judge")

# Fixed set, in this order. A FAIL or ERROR case gets the ones that apply.
CATEGORIES = ("error", "rate_limit", "retrieval", "generation", "forbidden", "no_visual",
              "wrong_visual", "judge")

_RATE_LIMIT = re.compile(r"\b429\b|rate[ _-]?limit", re.IGNORECASE)


def group_of(case_id: str) -> str:
    """A1 for Q1–Q10, A2 for Q11–Q18 (Q12a, Q12b, … included), else "other"."""
    m = re.match(r"Q(\d+)", case_id)
    n = int(m.group(1)) if m else 0
    return "A1" if 1 <= n <= 10 else "A2" if 11 <= n <= 18 else "other"


# ---------------------------------------------------------------------------
# Metric records
# ---------------------------------------------------------------------------

def metric_name(metric) -> str:
    """"Judge [GEval]" -> "Judge"."""
    return metric.__name__.split(" [")[0]


def metric_status(metric) -> Status:
    if metric.skipped:
        return Status.SKIP
    if metric.error:
        return Status.ERROR
    return Status.PASS if metric.success else Status.FAIL


def metric_record(metric) -> dict:
    """deepeval MetricData field names, plus `version`, `status` and `details`."""
    status = metric_status(metric)
    scored = status in (Status.PASS, Status.FAIL)
    return {
        "name": metric_name(metric),
        "version": getattr(metric, "version", None),
        "status": status,
        "score": round(float(metric.score), 4) if scored and metric.score is not None else None,
        "threshold": metric.threshold,
        "success": None if status is Status.SKIP else status is Status.PASS,
        "reason": metric.reason,
        "error": metric.error,
        "evaluation_model": metric.evaluation_model,
        "details": getattr(metric, "details", None) or {},
    }


# ---------------------------------------------------------------------------
# Case status, score, categories
# ---------------------------------------------------------------------------

def case_status(errored: bool, metrics: list[dict]) -> Status:
    """ERROR (ask raised, Answer.error, or a dependency errored) > FAIL (any metric FAIL) > PASS."""
    if errored:
        return Status.ERROR
    if any(m["status"] == Status.FAIL for m in metrics):
        return Status.FAIL
    return Status.PASS


def case_score(metrics: list[dict]) -> float | None:
    """Mean score of the metrics that are not SKIP and not ERROR. None if there are none."""
    scores = [m["score"] for m in metrics if m["status"] in (Status.PASS, Status.FAIL)]
    return round(sum(scores) / len(scores), 4) if scores else None


def incomplete(status: Status, metrics: list[dict]) -> bool:
    """A metric errored but the case did not."""
    return status != Status.ERROR and any(m["status"] == Status.ERROR for m in metrics)


def categories(status: Status, errors: list[str], metrics: list[dict]) -> list[str]:
    """Failure categories of a FAIL or ERROR case (empty for PASS). `errors`: the case's error
    texts (exception, Answer.error, dependency); metric errors are read from `metrics`."""
    if status == Status.PASS:
        return []
    found = set()
    if errors:
        found.add("error")
    texts = errors + [m["error"] for m in metrics if m.get("error")]
    if any(_RATE_LIMIT.search(t) for t in texts):
        found.add("rate_limit")
    by_name = {m["name"]: m for m in metrics}
    fact = by_name.get("FactRecall")
    if fact and fact["status"] == Status.FAIL:
        for item in fact["details"].get("missing", []):
            found.add("generation" if item["in_tool_results"] else "retrieval")
        if fact["details"].get("forbidden"):
            found.add("forbidden")
    visual = by_name.get("VisualMatch")
    if visual and visual["status"] == Status.FAIL:
        found.add("wrong_visual" if visual["details"].get("actual") else "no_visual")
    judge = by_name.get("Judge")
    if judge and judge["status"] == Status.FAIL:
        found.add("judge")
    return [c for c in CATEGORIES if c in found]


# ---------------------------------------------------------------------------
# Totals over case records (the `case` lines of a run log)
# ---------------------------------------------------------------------------

def _counts(cases: list[dict]) -> dict:
    n = Counter(c["status"] for c in cases)
    out = {s: n.get(s, 0) for s in (Status.PASS, Status.FAIL, Status.ERROR)}
    judged = out[Status.PASS] + out[Status.FAIL]
    return {**out, "pass_rate": round(out[Status.PASS] / judged, 4) if judged else None}


def summarize(cases: list[dict]) -> dict:
    """Totals, pass rate, mean metric scores, per group and per category. Dependency runs
    (`as_dependency`) are not counted."""
    scored = [c for c in cases if not c.get("as_dependency")]
    counts = _counts(scored)
    means = {}
    for name in METRIC_NAMES:
        scores = [m["score"] for c in scored for m in c["metrics"]
                  if m["name"] == name and m["status"] in (Status.PASS, Status.FAIL)]
        means[name] = round(sum(scores) / len(scores), 4) if scores else None
    groups = sorted({c["group"] for c in scored})
    category_counts = Counter(cat for c in scored for cat in c["categories"])
    return {
        "cases": len(scored),
        "totals": {s: counts[s] for s in (Status.PASS, Status.FAIL, Status.ERROR)},
        "pass_rate": counts["pass_rate"],
        "incomplete": sum(bool(c.get("incomplete")) for c in scored),
        "mean_scores": means,
        "by_group": {g: _counts([c for c in scored if c["group"] == g]) for g in groups},
        "category_counts": dict(category_counts.most_common()),
    }


def pass_line(totals: dict) -> str:
    """"7/10 pass · 2 fail · 1 error"."""
    p, f, e = (totals.get(s, 0) for s in (Status.PASS, Status.FAIL, Status.ERROR))
    return f"{p}/{p + f + e} pass · {f} fail · {e} error"


def case_order(case_id: str) -> tuple:
    """Q2 before Q10; Q12a before Q12b."""
    m = re.match(r"([A-Za-z]*)(\d+)(.*)", case_id)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (case_id, 0, "")
