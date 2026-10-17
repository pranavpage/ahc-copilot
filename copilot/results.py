"""Result store: data tools put rows here; visuals refer to them by result_id.

In memory for now (PLAN-UI.md: per conversation, in memory + SQLite later).
"""

import uuid

_store: dict[str, tuple[str, list[dict]]] = {}


def put(kind: str, rows: list[dict]) -> str:
    """Store rows and return a short result_id, e.g. 'r_3f9a'."""
    while True:
        result_id = f"r_{uuid.uuid4().hex[:4]}"
        if result_id not in _store:
            _store[result_id] = (kind, rows)
            return result_id


def get(result_id: str) -> list[dict]:
    """Rows stored under result_id. KeyError if unknown."""
    return _store[result_id][1]


def clear() -> None:
    """Drop all stored results."""
    _store.clear()
