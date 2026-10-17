"""SQLite access for the tools. Built by `db/load.py`."""

import sqlite3
from contextlib import closing

from copilot.config import get_settings


def connect(read_only: bool = True) -> sqlite3.Connection:
    """Open the copilot database. Read-only by default (URI mode=ro)."""
    path = get_settings().db_path
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def rows(sql: str, params: tuple | dict = ()) -> list[dict]:
    """Run a read-only query and return the rows as dicts."""
    with closing(connect()) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def today() -> str:
    """'Today' for the copilot (YYYY-MM-DD), from the `settings` table."""
    return rows("SELECT value FROM settings WHERE key = 'today'")[0]["value"]
