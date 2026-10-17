"""Export the final-question threads from the running LangGraph server to an answer sheet.

Use it after `seed_demo.py --final`, so the answer sheet shows the same answers as the web UI.

    uv run python scripts/export_threads.py            # runs/demo/<timestamp>/answers.md + answers.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, convert_to_messages
from langgraph_sdk import get_sync_client

from run_final import ROOT, block_md

sys.path.insert(0, str(ROOT))
from copilot.api import build_answer  # noqa: E402

NAMES = {"U-201": "Michael Turner", "U-301": "Robert Hayes", "U-401": "Laura Simmons", "U-402": "Chris Dalton",
         "U-501": "Olivia Grant", "U-601": "Nathan Pierce"}


def turns(messages: list) -> list[list]:
    """The messages of a thread, split into turns (each starts with a user message)."""
    out = []
    for m in messages:
        if isinstance(m, HumanMessage) or not out:
            out.append([])
        out[-1].append(m)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:2024")
    args = p.parse_args()
    client = get_sync_client(url=args.url)

    threads = [t for t in client.threads.search(limit=200)
               if (t["metadata"] or {}).get("title", "").split(":")[0].startswith("Q")]
    threads.sort(key=lambda t: (int(t["metadata"]["title"].split(":")[0][1:]), t["created_at"]))

    records, turn_no = [], {}
    for t in threads:
        q, user_id = t["metadata"]["title"].split(":")[0], t["metadata"]["user_id"]
        for turn in turns(convert_to_messages((t["values"] or {}).get("messages", []))):
            turn_no[q] = turn_no.get(q, 0) + 1
            a = build_answer(turn)
            records.append({"question": q, "turn": turn_no[q], "user": NAMES.get(user_id, user_id),
                            "user_id": user_id, "thread_id": t["thread_id"], "text": turn[0].content,
                            **a.model_dump(exclude={"trace"})})

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "runs" / "demo" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answers.json").write_text(json.dumps(records, indent=1, ensure_ascii=False, default=str))
    lines = ["# Final questions: full answers (web UI threads)", ""]
    for r in records:
        lines += [f"## {r['question']} turn {r['turn']} — {r['user']} ({r['user_id']})",
                  f"_Thread: {r['thread_id']}_", "", f"> {r['text']}", "", r["answer"] or "_(empty)_", ""]
        lines += [x for b in r["blocks"] for x in (block_md(b), "")]
        if r["tool_calls"]:
            lines += ["<details><summary>Tool calls and citations</summary>", ""]
            lines += [f"- `{c['name']}({json.dumps(c['args'], ensure_ascii=False)})`" for c in r["tool_calls"]]
            if r["citations"]:
                lines += ["", "Citations: " + ", ".join(r["citations"][:80])]
            lines += ["", "</details>", ""]
        if r["verification"]:
            lines += [f"_Check: {r['verification'].get('status')} — {r['verification'].get('summary', '')}_", ""]
    (out_dir / "answers.md").write_text("\n".join(lines))
    print(f"{len(records)} turns from {len(threads)} threads: {out_dir / 'answers.md'}")


if __name__ == "__main__":
    main()
