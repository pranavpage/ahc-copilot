"""Every test runs on a temp copy of the database, so memory writes never reach data/copilot.db.

The unit tests are written against the sample data: `data/sample.db`
(`uv run python db/load.py --sample --db data/sample.db`). Set DB_PATH to override.
"""

import os

import pytest

os.environ.setdefault("DB_PATH", "data/sample.db")

from evals.runner import isolated_db


@pytest.fixture(scope="session", autouse=True)
def _db_copy():
    with isolated_db() as path:
        yield path
