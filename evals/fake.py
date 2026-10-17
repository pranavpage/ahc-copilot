"""Fake ask() for offline runs: EVAL_ASK=evals.fake:ask uv run pytest evals

No LLM, no database. Each answer has a short trace and puts its tool rows in the result store,
so the report can show the timeline and tell retrieval misses from generation misses.
- Q1: a correct canned answer (PASS).
- ERROR_CASE: Answer.error with a 429 (ERROR, categories error + rate_limit).
- Every other case: a wrong answer (FAIL). Its one tool call returns the case's first
  must_include item, which the answer leaves out (generation); the other items are in no
  tool result (retrieval).
"""

import json

from copilot import results
from copilot.api import Answer, ToolCall
from evals.cases import EvalCase, load_cases

MODEL = "fake"
ERROR_CASE = "Q10"

Q1_ROWS = [{"asset_id": "WELL-0001", "is_producing": 0, "recorded_status": "active",
            "inspection_id": "INS-0001-0203", "inspected_by": "Ryan Brooks", "temp_delta_c": 3.2,
            "producing_threshold_c": 15.0}]

Q1_TEXT = (
    "**No, WELL-0001 is not producing oil.** The latest inspection, INS-0001-0203 on "
    "15 Oct 2026, was a drone inspection by Ryan Brooks. The wellhead was only 3.2 °C "
    "warmer than the air, below the T200 limit of 15 °C.\n\n"
    "Reason: note CTX-0001-003 by Jake Morales records a planned shut-in from 7 Oct for "
    "rod string replacement, expected back around 20 Oct. It is not yet in the "
    "maintenance system.\n\n"
    "The recorded status still says `active`, which is out of date."
)

WRONG_TEXT = "I could not find anything about that."


def _dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _ai(text: str = "", calls: list[dict] = (), reasoning: str | None = None) -> dict:
    return {"kind": "ai", "text": text, "reasoning": reasoning, "tool_calls": list(calls),
            "model": MODEL, "usage": {"input_tokens": 1200, "output_tokens": 40},
            "finish_reason": "tool_calls" if calls else "stop"}


def _tool(call_id: str, name: str, content: dict) -> dict:
    return {"kind": "tool", "tool_call_id": call_id, "name": name, "content": _dumps(content),
            "status": "ok"}


def _data_call(question: str, call_id: str, name: str, args: dict, rows: list[dict],
               ids: list[str]) -> tuple[ToolCall, list[dict]]:
    """A data tool call: rows go to the result store; returns the ToolCall and its trace steps."""
    rid = results.put(name, rows)
    content = {"result_id": rid, "row_count": len(rows), "rows": rows, "ids": ids, "notes": [],
               "truncated": False}
    call = {"id": call_id, "name": name, "args": args}
    steps = [_ai("", [call], reasoning=f"I need {name} to answer: {question[:60]}"),
             _tool(call_id, name, content)]
    return ToolCall(name=name, args=args, result_id=rid), steps


def q1_answer(question: str) -> Answer:
    call, steps = _data_call(question, "fake-1", "well_status", {"asset_ids": ["WELL-0001"]},
                             Q1_ROWS, ["INS-0001-0203", "CTX-0001-003"])
    block = {"type": "status_card", "title": "WELL-0001: not producing", "source": call.result_id,
             "fields": {"asset_id": "WELL-0001"}, "rows": Q1_ROWS}
    visual = {"id": "fake-2", "name": "show_visual",
              "args": {"type": "status_card", "title": block["title"], "source": call.result_id,
                       "fields": block["fields"]}}
    trace = [{"kind": "user", "text": question}, *steps,
             _ai("", [visual]), _tool("fake-2", "show_visual", {**visual["args"], "row_count": 1,
                                                                 "shown": True}),
             _ai(Q1_TEXT)]
    return Answer(answer=Q1_TEXT, blocks=[block], citations=["INS-0001-0203", "CTX-0001-003"],
                  tool_calls=[call, ToolCall(name="show_visual", args=visual["args"], result_id=None)],
                  model=MODEL, error=None, trace=trace)


def wrong_answer(question: str, case: EvalCase | None) -> Answer:
    first = case.must_include[0] if case and case.must_include else None
    first = first[0] if isinstance(first, list) else first
    rows = [{"query": question[:40], "match": first}] if first else []
    call, steps = _data_call(question, "fake-1", "search_docs", {"query": question[:40]}, rows, [])
    trace = [{"kind": "user", "text": question}, *steps, _ai(WRONG_TEXT)]
    return Answer(answer=WRONG_TEXT, blocks=[], citations=[], tool_calls=[call], model=MODEL,
                  error=None, trace=trace)


def error_answer(question: str) -> Answer:
    return Answer(answer="", blocks=[], citations=[], tool_calls=[], model=MODEL,
                  error="RateLimitError: Error code: 429 (fake)",
                  trace=[{"kind": "user", "text": question}])


def _case_for(message: str) -> EvalCase | None:
    """The case whose question, or last turn, is this message."""
    message = message.strip()
    for c in load_cases():
        last = c.question if c.question is not None else c.turns[-1].message
        if (last or "").strip() == message:
            return c
    return None


def ask(question: str, user_id: str, thread_id: str | None = None) -> Answer:
    """Same signature as copilot.api.ask."""
    case = _case_for(question)
    if case is not None and case.id == "Q1":
        return q1_answer(question)
    if case is not None and case.id == ERROR_CASE:
        return error_answer(question)
    return wrong_answer(question, case)
