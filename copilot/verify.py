"""Checks each answer against the tool results before the user sees it. Owner: D.

The checks are code, not a model, so they are exact:
- ids:     every record ID in the answer is in a tool result (or the question).
- numbers: every number in the answer is in a tool result, the question or the system prompt.
- lists:   a list answer names every item of the tool result it comes from.
- groups:  an answer from `find_mentions` names every group and gives the totals.
- notes:   a tool note marked "(say so)" / "(state them)" is stated: its IDs, names and measured values.

`check()` returns a record: {"status": "passed" | "failed", "checked": {...}, "problems": [...]}.
The agent sends a failed answer back to the model once (copilot/agent.py), then shows the record.
"""

import json
import re

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from copilot import db, results

TOOL_NAME = "verify_answer"

ID = re.compile(r"\b(?:WELL-\d{4}|INS-\d{4}-\d{4}|MNT-\d{4}-\d{3}|REG-\d{4}-\d{3}|CTX-\d{4}-\d{3}"
                r"|COR-(?:CTX-)?\d{4}-\d{3}|NOTE-\d{4}-\d{3}|(?:SR|RC|WS)-\d{2}|U-\d{3})\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:]+Z?)?\b")
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.,])-?\d+(?:\.\d+)?(?![\w])")
SMALL = 12          # small whole numbers (counts, months, "3 wells") are not checked
MAX_TOKENS = 8      # a "(say so)" note with more required tokens than this only needs its IDs

# Tool results whose rows are the answer's list, and the key that names each row.
LIST_KEYS = {
    "well_status": ("asset_id", lambda a: a.get("not_producing_only") or a.get("asset_ids")),
    "spills": ("inspection_id", lambda a: not a.get("group_by")),
    "downtime": ("asset_id", lambda a: a.get("top_n") or a.get("asset_id")),
    "rca_due": ("asset_id", lambda a: True),
    "repair_costs": ("asset_id", lambda a: True),
}
MAX_LIST = 30       # longer results are not lists that one answer names in full


def _text(m: AnyMessage) -> str:
    if isinstance(m.content, str):
        return m.content
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in m.content)


def _turn_start(messages: list[AnyMessage]) -> int:
    return max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=0)


def answer_message(messages: list[AnyMessage]) -> AIMessage | None:
    """The answer of the latest turn: the last AI message with text (some models write the answer
    next to the show_visual call and end with an empty message)."""
    turn = messages[_turn_start(messages):]
    return next((m for m in reversed(turn) if isinstance(m, AIMessage) and _text(m).strip()), None)


def rounds(messages: list[AnyMessage]) -> int:
    """How many times this turn's answer was already checked."""
    return sum(1 for m in messages[_turn_start(messages):] if isinstance(m, ToolMessage) and m.name == TOOL_NAME)


def _number(s: str) -> float:
    return float(s.replace(",", ""))


def _numbers(text: str) -> list[str]:
    return NUMBER.findall(text)


def _matches(value: str, evidence: set[float]) -> bool:
    """'21.1' matches 21.08 (rounded to the answer's decimals); '25,794' matches 25794.0."""
    v = _number(value)
    decimals = len(value.split(".")[1]) if "." in value else 0
    return any(abs(round(e, decimals) - v) < 1e-9 or abs(e - v) < 1e-9 for e in evidence)


def _tool_results(messages: list[AnyMessage]) -> list[dict]:
    """Every data tool result in the thread: name, args, full rows, ids, notes, and whether it is
    from this turn."""
    start = _turn_start(messages)
    args = {c["id"]: c for m in messages if isinstance(m, AIMessage) for c in m.tool_calls}
    out = []
    for i, m in enumerate(messages):
        if not isinstance(m, ToolMessage) or m.name in (TOOL_NAME, "show_visual"):
            continue
        art = m.artifact if isinstance(m.artifact, dict) else {}
        try:
            rows = results.get(art["result_id"]) if art.get("result_id") else []
        except KeyError:            # the result store is per process; fall back to what the model saw
            rows = (json.loads(_text(m)) or {}).get("rows", []) if _text(m).startswith("{") else []
        out.append({"name": m.name, "args": (args.get(m.tool_call_id) or {}).get("args", {}),
                    "rows": rows, "ids": art.get("ids", []), "notes": art.get("notes", []),
                    "text": _text(m), "this_turn": i > start})
    return out


def _user_names() -> list[str]:
    return [u["name"] for u in db.rows("SELECT name FROM users")]


def _required(note: str, names: list[str]) -> list[str]:
    """What an answer must contain to state a "(say so)" note: IDs, people, measured values."""
    ids = list(dict.fromkeys(ID.findall(note)))
    people = [n for n in names if n in note]
    values = [v for v in _numbers(ISO_DATE.sub(" ", note)) if "." in v]
    tokens = list(dict.fromkeys(ids + people + values))
    return tokens if len(tokens) <= MAX_TOKENS else ids


def _mentions(answer: str, token: str) -> bool:
    if NUMBER.fullmatch(token):
        return _matches(token, {_number(v) for v in _numbers(answer)})
    return token.lower() in answer.lower()


def check(messages: list[AnyMessage], context: str = "") -> dict:
    """Check the latest answer in `messages` against the thread's tool results.
    `context`: other text the answer may use (the system prompt: today, users, areas)."""
    msg = answer_message(messages)
    answer = _text(msg) if msg else ""
    problems: list[str] = []
    checked = {"ids": 0, "numbers": 0, "lists": 0, "groups": 0, "notes": 0}
    if not answer.strip():
        return {"status": "failed", "checked": checked, "problems": ["the answer is empty"]}

    tools = _tool_results(messages)
    questions = " ".join(_text(m) for m in messages if isinstance(m, HumanMessage))
    evidence_text = " ".join([questions, context] + [t["text"] for t in tools]
                             + [json.dumps(t["rows"], default=str) for t in tools]
                             + [" ".join(t["ids"] + t["notes"]) for t in tools])
    evidence_numbers = {_number(v) for v in _numbers(evidence_text)}
    for t in tools:
        evidence_numbers |= {float(len(t["rows"]))}

    # IDs
    ids = list(dict.fromkeys(ID.findall(answer)))
    checked["ids"] = len(ids)
    unknown = [i for i in ids if i not in evidence_text]
    if unknown:
        problems.append(f"these IDs are in no tool result: {', '.join(unknown)}. Remove them or call a tool")

    # Numbers (dates and IDs taken out first)
    plain = ISO_DATE.sub(" ", ID.sub(" ", answer))
    values = [v for v in _numbers(plain) if "." in v or abs(_number(v)) > SMALL]
    checked["numbers"] = len(values)
    unsupported = list(dict.fromkeys(v for v in values if not _matches(v, evidence_numbers)))
    if unsupported:
        problems.append(f"these numbers are in no tool result: {', '.join(unsupported)}. Take every number "
                        "from a tool result; do not compute sums or averages yourself")
    dates = [d[:10] for d in ISO_DATE.findall(answer)]
    bad_dates = list(dict.fromkeys(d for d in dates if d not in evidence_text))
    if bad_dates:
        problems.append(f"these dates are in no tool result: {', '.join(bad_dates)}")

    names = _user_names()
    for t in (t for t in tools if t["this_turn"]):
        # Lists: name every row, or say "k of n"
        key, applies = LIST_KEYS.get(t["name"], (None, None))
        if key and applies(t["args"]) and 1 < len(t["rows"]) <= MAX_LIST:
            keys = list(dict.fromkeys(r[key] for r in t["rows"] if r.get(key)))
            named = [k for k in keys if k in answer]
            if named:
                checked["lists"] += 1
                missing = [k for k in keys if k not in answer]
                if missing and not re.search(rf"\b{len(named)}\s+of\s+{len(keys)}\b", answer):
                    problems.append(f"the {t['name']} result has {len(keys)} items but the answer names "
                                    f"{len(named)}; missing: {', '.join(missing)}. Name them all, or say "
                                    f"'{len(named)} of {len(keys)}' and why")
        # find_mentions: every group named, totals given
        if t["name"] == "find_mentions" and t["rows"]:
            checked["groups"] += len(t["rows"])
            missing = [r["group"] for r in t["rows"] if r["group"] != "other"
                       and not all(w in answer.lower() for w in r["group"].lower().split()
                                   if w not in t["args"].get("terms", []))]
            if missing:
                problems.append("these find_mentions groups are not in the answer: " + "; ".join(missing)
                                + ". Name each one, or say why it is left out (e.g. the word used in general)")
            total = next((n for n in t["notes"] if " mentions of " in n), "")
            counts = _numbers(total)[:2]
            if counts and not all(_mentions(answer, c) for c in counts):
                problems.append(f"give the totals of the search: {', '.join(counts)} (mentions, records), "
                                "so the user knows all the data was searched")
        # Notes the answer must state
        for note in t["notes"]:
            if "(say so)" not in note and "(state them)" not in note:
                continue
            checked["notes"] += 1
            missing = [tok for tok in _required(note, names) if not _mentions(answer, tok)]
            if missing:
                problems.append(f"state this tool note in the answer: \"{note}\" (missing: {', '.join(missing)})")

    return {"status": "failed" if problems else "passed", "checked": checked, "problems": problems}


def summary(record: dict) -> str:
    """'passed: 8 IDs, 12 numbers, 1 list checked' / 'failed: 2 problems'."""
    c = record["checked"]
    done = ", ".join(f"{n} {k}" for k, n in c.items() if n)
    if record["status"] == "passed":
        return f"verified against the tool results: {done or 'nothing to check'}"
    return f"not verified: {len(record['problems'])} problem(s) ({done} checked)"
