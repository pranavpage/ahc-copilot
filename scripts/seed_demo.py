"""Seed a demo: ask questions through the running LangGraph server, so the web UI lists the threads.

The threads carry `user_id` and `title` in their metadata, so the web UI lists them for that user.

Eval questions (default): one thread per question, all as one user. Only read-only cases by
default: the feedback cases (Q12+) change the shared database, so ask those live in the demo.

Final questions (--final): the 11 questions of test-data/final-questions.md (turns from
scripts/run_final.py), each as its named user. "Same session" turns share a thread, "new session"
turns get a new one. Q8 writes notes and a preference to data/copilot.db (that is what it tests),
and Q9 reads them, so Q8 and Q9 run in order.

    uv run langgraph dev --no-browser --port 2024 --allow-blocking   # in another terminal
    uv run python scripts/seed_demo.py                                # Q1-Q10, Q14a, Q18 as U-201
    uv run python scripts/seed_demo.py --cases Q1 Q2 --user U-202
    uv run python scripts/seed_demo.py --final                        # all final questions
    uv run python scripts/seed_demo.py --final --cases Q3 Q10
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from langgraph_sdk import get_sync_client

from run_final import CHAINED, TURNS, U

CASES = Path(__file__).resolve().parent.parent / "evals" / "cases.yaml"
DEFAULT_CASES = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Q14a", "Q18"]


def questions(case_ids: list[str]) -> list[tuple[str, str]]:
    cases = {c["id"]: c for c in yaml.safe_load(CASES.read_text())}
    out = []
    for cid in case_ids:
        c = cases[cid]
        out.append((cid, c.get("question") or c["turns"][0]["message"]))
    return out


def final_chains(question_ids: list[str] | None) -> list[list[tuple]]:
    """The final-question turns, in order, grouped so that each group can run on its own."""
    chains: dict[str, list] = {}
    for turn in TURNS:
        if not question_ids or turn[0] in question_ids:
            chains.setdefault(CHAINED.get(turn[0], turn[0]), []).append(turn)
    return list(chains.values())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:2024")
    p.add_argument("--user", default="U-201")
    p.add_argument("--cases", nargs="+")
    p.add_argument("--final", action="store_true", help="seed the final questions, each as its named user")
    p.add_argument("--parallel", type=int, default=4)
    args = p.parse_args()
    client = get_sync_client(url=args.url)

    def ask(thread_id: str, user_id: str, question: str) -> str:
        run = client.runs.create(thread_id, "copilot",
                                 input={"messages": [{"role": "user", "content": question}]},
                                 config={"configurable": {"x-user-id": user_id}})
        client.runs.join(thread_id, run["run_id"])
        return client.runs.get(thread_id, run["run_id"])["status"]

    def seed(item: tuple[str, str]) -> str:
        cid, question = item
        thread = client.threads.create(metadata={"user_id": args.user, "title": question[:120]})
        status = ask(thread["thread_id"], args.user, question)
        return f"{cid:5} {status:8} {thread['thread_id']}  {question[:70]}"

    def seed_chain(chain: list[tuple]) -> str:
        threads: dict[str, str] = {}
        lines = []
        for q, t, user, session, text in chain:
            if session not in threads:
                meta = {"user_id": U[user], "title": f"{q}: {text}"[:120]}
                threads[session] = client.threads.create(metadata=meta)["thread_id"]
            status = ask(threads[session], U[user], text)
            lines.append(f"{q}.{t:<2} {status:8} {U[user]} {threads[session]}  {text[:60]}")
        return "\n".join(lines)

    with ThreadPoolExecutor(args.parallel) as pool:
        if args.final:
            results = pool.map(seed_chain, final_chains(args.cases))
        else:
            results = pool.map(seed, questions(args.cases or DEFAULT_CASES))
        for line in results:
            print(line, flush=True)


if __name__ == "__main__":
    main()
