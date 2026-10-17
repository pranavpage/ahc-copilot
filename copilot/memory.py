"""Private memory per user: who is talking, and an index of their past conversations.

The LangGraph checkpointer keeps the full messages of one thread. This module keeps, in SQLite,
what later chats need to find it again: one `conversations` row per thread, the question and the
final answer of each turn (`messages`), and the IDs that each answer named, in order
(`conversation_entities`). "The three wells we discussed yesterday" resolves from these rows.

Every read is filtered by the user who asks. The user ID always comes from the run config,
never from the model.
"""

import re
from contextlib import closing
from datetime import UTC, datetime

from copilot import db

EXCERPT_CHARS = 400        # characters of each answer kept for recall

# Record IDs that an answer can name. Areas are matched by name or ID from the `areas` table.
_ENTITY_PATTERNS = {
    "well": re.compile(r"\bWELL-\d{4}\b"),
    "inspection": re.compile(r"\bINS-\d{4}-\d{4}\b"),
    "maintenance": re.compile(r"\bMNT-\d{4}-\d{3}\b"),
    "event": re.compile(r"\bREG-\d{4}-\d{3}\b"),
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def user_profile(user_id: str | None) -> dict | None:
    """Name, role, team and areas of a user, or None if the ID is unknown."""
    if not user_id:
        return None
    found = db.rows(
        """
        SELECT u.user_id, u.name, u.role, t.name AS team_name,
               (SELECT COUNT(*) FROM wells w WHERE w.in_charge_user_id = u.user_id) AS wells_in_charge
        FROM users u LEFT JOIN teams t ON t.team_id = u.team_id
        WHERE u.user_id = ?
        """,
        (user_id,),
    )
    if not found:
        return None
    profile = found[0]
    profile["areas"] = db.rows(
        "SELECT a.area_id, a.name FROM areas a JOIN users u ON u.team_id = a.team_id "
        "WHERE u.user_id = ? ORDER BY a.name",
        (user_id,),
    )
    return profile


def entities(text: str) -> list[tuple[str, str]]:
    """(entity_type, entity_id) named in the text, in order of first mention, no duplicates."""
    found: dict[tuple[str, str], int] = {}
    for kind, pattern in _ENTITY_PATTERNS.items():
        for m in pattern.finditer(text):
            found.setdefault((kind, m.group()), m.start())
    for a in db.rows("SELECT area_id, name FROM areas"):
        for name in (a["name"], a["area_id"]):
            if m := re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                key = ("area", a["area_id"])
                found[key] = min(found.get(key, m.start()), m.start())
    return sorted(found, key=found.get)


def remember(thread_id: str, user_id: str, question: str, answer: str) -> None:
    """Index one finished turn. Skips unknown users, and threads that belong to another user."""
    if not thread_id or not user_profile(user_id) or not answer.strip():
        return
    now = _now()
    with closing(db.connect(read_only=False)) as conn, conn:
        owner = conn.execute("SELECT user_id FROM conversations WHERE conversation_id = ?",
                             (thread_id,)).fetchone()
        if owner is None:
            conn.execute("INSERT INTO conversations (conversation_id, user_id, started_at, title) "
                         "VALUES (?, ?, ?, ?)", (thread_id, user_id, now, question.strip()[:120]))
        elif owner["user_id"] != user_id:
            return
        conn.execute("INSERT INTO messages (conversation_id, created_at, role, content) VALUES (?, ?, 'user', ?)",
                     (thread_id, now, question))
        message_id = conn.execute(
            "INSERT INTO messages (conversation_id, created_at, role, content) VALUES (?, ?, 'assistant', ?)",
            (thread_id, now, answer)).lastrowid
        conn.executemany(
            "INSERT INTO conversation_entities (conversation_id, message_id, entity_type, entity_id, rank, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(thread_id, message_id, kind, eid, rank, now)
             for rank, (kind, eid) in enumerate(entities(answer), start=1)],
        )


def recall(user_id: str, exclude_thread_id: str | None = None, query: str | None = None,
           limit: int = 5) -> list[dict]:
    """This user's earlier conversations, newest first, each with its turns and the IDs it named.

    `query` keeps the conversations whose text or entities contain any of its words.
    """
    convs = db.rows(
        "SELECT conversation_id, started_at, title FROM conversations "
        "WHERE user_id = ? AND conversation_id <> coalesce(?, '') ORDER BY started_at DESC, rowid DESC",
        (user_id, exclude_thread_id),
    )
    words = [w.lower() for w in re.findall(r"[\w-]+", query or "") if len(w) > 2]
    out = []
    for c in convs:
        msgs = db.rows("SELECT message_id, role, content FROM messages WHERE conversation_id = ? "
                       "ORDER BY message_id", (c["conversation_id"],))
        ents = db.rows("SELECT entity_type, entity_id, message_id FROM conversation_entities "
                       "WHERE conversation_id = ? ORDER BY message_id, rank", (c["conversation_id"],))
        if words:
            text = " ".join([c["title"] or ""] + [m["content"] for m in msgs]
                            + [e["entity_id"] for e in ents]).lower()
            if not any(w in text for w in words):
                continue
        turns, question = [], None
        for m in msgs:
            if m["role"] == "user":
                question = m["content"]
            elif m["role"] == "assistant":
                named = [e for e in ents if e["message_id"] == m["message_id"]]
                turns.append({
                    "question": question,
                    "answer_excerpt": m["content"][:EXCERPT_CHARS],
                    "wells": [e["entity_id"] for e in named if e["entity_type"] == "well"],
                    "other_ids": [e["entity_id"] for e in named if e["entity_type"] != "well"],
                })
        out.append({"conversation_id": c["conversation_id"], "started_at": c["started_at"],
                    "date": c["started_at"][:10], "title": c["title"], "turns": turns})
        if len(out) >= limit:
            break
    return out
