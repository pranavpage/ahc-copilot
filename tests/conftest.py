"""Every test runs on a temp copy of the database, so memory writes never reach data/copilot.db."""

import pytest

from evals.runner import isolated_db


@pytest.fixture(scope="session", autouse=True)
def _db_copy():
    with isolated_db() as path:
        yield path
