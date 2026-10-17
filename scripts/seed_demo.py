"""Seed a demo: ask eval questions through the running LangGraph server, one thread per question.

The threads carry `user_id` and `title` in their metadata, so the web UI lists them for that user.
Only read-only cases by default: the feedback cases (Q12+) change the shared database, so ask
those live in the demo.

    uv run langgraph dev --no-browser --port 2024 --allow-blocking   # in another terminal
    uv run python scripts/seed_demo.py                                # Q1-Q10, Q14a, Q18 as U-201
    uv run python scripts/seed_demo.py --cases Q1 Q2 --user U-202
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from langgraph_sdk import get_sync_client

CASES = Path(__file__).resolve().parent.parent / "evals" / "cases.yaml"
DEFAULT_CASES = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Q14a", "Q18"]


def questions(case_ids: list[str]) -> list[tuple[str, str]]:
    cases = {c["id"]: c for c in yaml.safe_load(CASES.read_text())}
    out = []
    for cid in case_ids:
        c = cases[cid]
        out.append((cid, c.get("question") or c["turns"][0]["message"]))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:2024")
    p.add_argument("--user", default="U-201")
    p.add_argument("--cases", nargs="+", default=DEFAULT_CASES)
    p.add_argument("--parallel", type=int, default=4)
    args = p.parse_args()
    client = get_sync_client(url=args.url)

    def seed(item: tuple[str, str]) -> str:
        cid, question = item
        thread = client.threads.create(metadata={"user_id": args.user, "title": question[:120]})
        run = client.runs.create(thread["thread_id"], "copilot",
                                 input={"messages": [{"role": "user", "content": question}]},
                                 config={"configurable": {"x-user-id": args.user}})
        client.runs.join(thread["thread_id"], run["run_id"])
        status = client.runs.get(thread["thread_id"], run["run_id"])["status"]
        return f"{cid:5} {status:8} {thread['thread_id']}  {question[:70]}"

    with ThreadPoolExecutor(args.parallel) as pool:
        for line in pool.map(seed, questions(args.cases)):
            print(line, flush=True)


if __name__ == "__main__":
    main()
