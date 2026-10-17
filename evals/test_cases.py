"""One test per eval case (parametrised in conftest.py). `pytest evals -k Q2` runs one case.

Options: --judge (add the GEval rubric judge), --cases A1 (only Q1–Q10) or --cases Q1,Q3.
`-k Q1` also matches Q10–Q18; use `--cases Q1` for exactly one case.
Offline: EVAL_ASK=evals.fake:ask uv run pytest evals
"""

import pytest

from evals.report import failure_block
from evals.schema import Status


def test_case(case, runner):
    res = runner.result(case.id)
    status = res.status
    if status == Status.FAIL:
        pytest.fail(failure_block(res.record()), pytrace=False)
    if status == Status.ERROR:
        pytest.fail("ERROR: " + failure_block(res.record()), pytrace=False)
