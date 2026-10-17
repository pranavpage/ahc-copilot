"""Eval runner. Owner: C. Placeholder: only checks that the cases load."""

from evals.cases import load_cases


def test_cases_load():
    assert load_cases()
