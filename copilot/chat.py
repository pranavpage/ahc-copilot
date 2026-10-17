"""Chat with the copilot in the terminal. Owner: D.

    uv run python -m copilot.chat --user U-201

Commands: /new (new thread), /user U-202 (change user, same thread), /quit.
"""

import argparse
import json
import uuid

from copilot.api import Answer, ask


def print_answer(a: Answer) -> None:
    if a.error:
        print(f"[error] {a.error}")
    print(a.answer or "(no answer)")
    for b in a.blocks:
        print(f"[visual] {b['type']}: {b['title']} ({len(b['rows'])} rows from {b['source']})")
    for c in a.tool_calls:
        rid = f" -> {c.result_id}" if c.result_id else ""
        print(f"[tool] {c.name}({json.dumps(c.args, ensure_ascii=False)}){rid}")
    if a.citations:
        print(f"[citations] {', '.join(a.citations)}")
    print(f"[model] {a.model}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default="U-201", help="user ID, e.g. U-201")
    user = parser.parse_args().user
    thread = uuid.uuid4().hex
    print(f"user {user}, thread {thread[:8]}. /new, /user <id>, /quit")

    while True:
        try:
            line = input(f"{user}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return
        if line == "/new":
            thread = uuid.uuid4().hex
            print(f"new thread {thread[:8]}")
            continue
        if line.startswith("/user"):
            parts = line.split()
            if len(parts) != 2:
                print("usage: /user U-202")
                continue
            user = parts[1]
            print(f"user {user}, same thread {thread[:8]}")
            continue
        print_answer(ask(line, user, thread))


if __name__ == "__main__":
    main()
