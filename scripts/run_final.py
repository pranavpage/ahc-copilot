"""Run the final questions (test-data/final-questions.md) through the copilot and save every answer.

    uv run python scripts/run_final.py                   # all turns, in order, one at a time
    uv run python scripts/run_final.py --only Q3,Q8      # some questions (still in order)
    uv run python scripts/run_final.py --workers 4       # questions in parallel (Q8 -> Q9 stay in order)

Each run works on a fresh copy of data/copilot.db (the test data), so memory starts empty and
the real DB is never written. "New session" = a new thread; "same session" = the same thread.
Output: runs/final/<timestamp>/answers.md (text, visuals as tables, tool calls, citations) and
answers.json. The markdown is the answer sheet to submit with the write-up.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

U = {"Michael Turner": "U-201", "Robert Hayes": "U-301", "Laura Simmons": "U-401", "Chris Dalton": "U-402",
     "Olivia Grant": "U-501", "Nathan Pierce": "U-601"}

# (question, turn, user, session, text). Same session key = same thread.
TURNS = [
    ("Q1", 1, "Michael Turner", "q1", "All our wells feed one reservoir. Map the reservoir pressure across the "
     "field from the pressure data."),
    ("Q2", 1, "Robert Hayes", "q2", "Which well produced the most oil in 2026?"),
    ("Q3", 1, "Laura Simmons", "q3", "Since 1 Nov 2026, every time an operator note reports gas at a well, did "
     "we get someone out to that well in time under our operating procedures? List every report and whether "
     "the response met the deadline."),
    ("Q4", 1, "Chris Dalton", "q4", "Across all areas, which temporary flowline bypasses are in place right now, "
     "and is each one allowed? Also list any bypass, past or present, that stayed in after its approval ran "
     "out or was never approved at all."),
    ("Q5", 1, "Michael Turner", "q5", "The State Oil & Gas Commission wrote to us in November 2026 about spills. "
     "Which of our spills does the letter cover, and on which ones are we not compliant? Show me a table."),
    ("Q6", 1, "Nathan Pierce", "q6", "Across the whole field, not just my area, for which wells do the latest "
     "inspection and the operator notes disagree about whether the well is producing oil? For each one, what "
     "is its real status right now, and why?"),
    ("Q7", 1, "Robert Hayes", "q7", "Over the last month the operators have written notes about wells that sound "
     "or behave wrong. Which of those wells haven't had a repair since? Rank the 10 most likely to need a "
     "repair in the next 90 days, other than a spill clean-up, and quote the notes as evidence."),
    ("Q7", 2, "Robert Hayes", "q7", "Which three would you send a crew to first this week, and why?"),
    ("Q8", 1, "Nathan Pierce", "q8a", "WELL-0333's recalled pump was swapped out yesterday. The work order isn't "
     "in the system yet. Please count it as replaced from now on."),
    ("Q8", 2, "Nathan Pierce", "q8a", "Also, just for me: whenever you list wells, sort them by area and then by "
     "well ID, and show costs in thousands of dollars."),
    ("Q8", 3, "Robert Hayes", "q8b", "Which recalled pumps are still in the ground right now?"),
    ("Q8", 4, "Olivia Grant", "q8c", "Nathan told me the recalled pump on WELL-0577 was swapped as well. Take it "
     "off the recall list."),
    ("Q8", 5, "Nathan Pierce", "q8d", "Show me the recalled pumps that are still in the ground in my area, and "
     "what it cost to install each one."),
    ("Q9", 1, "Robert Hayes", "q9", "How many recalled pumps are still in the ground, and in which areas?"),
    ("Q9", 2, "Robert Hayes", "q9", "Different topic. Who leads Northwest Production, and how many wells does "
     "that team run?"),
    ("Q9", 3, "Robert Hayes", "q9", "What does our operations SOP say about cold weather? Name one well that "
     "missed the check in December."),
    ("Q9", 4, "Robert Hayes", "q9", "An operator reported a gas smell at WELL-0332 on 3 Dec. What was the H2S "
     "reading?"),
    ("Q9", 5, "Robert Hayes", "q9", "Back to the pumps from my first question: which of those wells are not "
     "producing oil right now, and when was each one last repaired?"),
    ("Q9", 6, "Robert Hayes", "q9", "Of all the wells we've talked about today, which one would you deal with "
     "first, and why?"),
    ("Q10", 1, "Michael Turner", "q10", "When a well stays shut in longer than the repair itself, what are we "
     "usually waiting on: parts, crews, contractors or weather? Break it down by area for jobs started in "
     "2026, with the typical number of extra days, and tell me if any area stands out."),
    ("Q11", 1, "Olivia Grant", "q11", "Which region of the field consistently runs hotter?"),
]
CHAINED = {"Q8": "Q8+Q9", "Q9": "Q8+Q9"}     # Q9 asks about pumps after Q8's memory writes


def fresh_db(out_dir: Path) -> Path:
    src = ROOT / "data" / "copilot.db"
    if not src.exists():
        sys.exit("data/copilot.db not found. Build it: uv run python db/load.py")
    dst = out_dir / "copilot.db"
    with closing(sqlite3.connect(f"file:{src}?mode=ro", uri=True)) as a, closing(sqlite3.connect(dst)) as b:
        a.backup(b)
    return dst


def md_table(rows: list[dict], columns: list[str] | None, limit: int = 60) -> str:
    if not rows:
        return "_(no rows)_"
    cols = columns or list(rows[0].keys())

    def cell(v):
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")[:300]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(cell(r.get(c)) for c in cols) + " |" for r in rows[:limit]]
    if len(rows) > limit:
        out.append(f"\n_({len(rows) - limit} more rows)_")
    return "\n".join(out)


def block_md(b: dict) -> str:
    f = b.get("fields") or {}
    cols = f.get("columns")
    if not cols:
        cols = [c for k in ("category", "series", "x", "y", "value", "label", "lat", "lon", "asset_id")
                for c in ([f[k]] if isinstance(f.get(k), str) else f.get(k) or [])] or None
        cols = list(dict.fromkeys(cols)) if cols else None
    return (f"**Visual: {b.get('type')}** — {b.get('title', '')}  \nfields: `{json.dumps(f)}`\n\n"
            + md_table(b.get("rows") or [], cols))


def run_chain(turns, threads, log):
    from copilot.api import ask
    out = []
    for q, t, user, session, text in turns:
        thread = threads.setdefault(session, f"final-{session}-{uuid.uuid4().hex[:6]}")
        t0 = time.time()
        a = ask(text, U[user], thread_id=thread)
        secs = round(time.time() - t0, 1)
        rec = {"question": q, "turn": t, "user": user, "user_id": U[user], "thread_id": thread, "text": text,
               "seconds": secs, **a.model_dump(exclude={"trace"})}
        out.append(rec)
        log(f"{q}.{t} {user}: {secs}s, {len(a.tool_calls)} tool calls"
            + (f", ERROR {a.error}" if a.error else ""))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated question IDs, e.g. Q3,Q8")
    ap.add_argument("--workers", type=int, default=1, help="questions in parallel (default 1 = strictly in order)")
    args = ap.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "runs" / "final" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(fresh_db(out_dir))
    from copilot.config import get_settings
    get_settings.cache_clear()
    from copilot import db

    wanted = set(args.only.split(",")) if args.only else None
    turns = [t for t in TURNS if not wanted or t[0] in wanted]
    chains: dict[str, list] = {}
    for t in turns:
        chains.setdefault(CHAINED.get(t[0], t[0]) if args.workers > 1 else "all", []).append(t)

    threads: dict[str, str] = {}
    print(f"DB copy: {os.environ['DB_PATH']} (today = {db.today()}), model {get_settings().model}")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(run_chain, c, threads, print) for c in chains.values()]
        records = [r for f in futures for r in f.result()]
    order = {(q, t): i for i, (q, t, *_rest) in enumerate(TURNS)}
    records.sort(key=lambda r: order[(r["question"], r["turn"])])

    (out_dir / "answers.json").write_text(json.dumps(records, indent=1, ensure_ascii=False, default=str))
    lines = [f"# Final questions — copilot answers", "",
             f"Run {stamp} · model `{get_settings().model}` · today = {db.today()} · test dataset", ""]
    for r in records:
        lines += [f"## {r['question']} turn {r['turn']} — {r['user']} ({r['user_id']})",
                  f"_Session: {r['thread_id']} · {r['seconds']} s_", "", f"> {r['text']}", "", r["answer"] or "_(empty)_", ""]
        for b in r["blocks"]:
            lines += [block_md(b), ""]
        if r["tool_calls"]:
            lines += ["<details><summary>Tool calls and citations</summary>", ""]
            lines += [f"- `{c['name']}({json.dumps(c['args'], ensure_ascii=False)})`" for c in r["tool_calls"]]
            if r["citations"]:
                lines += ["", "Citations: " + ", ".join(r["citations"][:80])]
            lines += ["", "</details>", ""]
        if r["error"]:
            lines += [f"**Error:** {r['error']}", ""]
    (out_dir / "answers.md").write_text("\n".join(lines))
    print(f"Done in {round(time.time() - t0)} s: {out_dir / 'answers.md'}")


if __name__ == "__main__":
    main()
