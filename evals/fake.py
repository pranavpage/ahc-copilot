"""Fake ask() for offline runs: EVAL_ASK=evals.fake:ask uv run pytest evals

A correct canned answer for Q1 and a wrong one for everything else, so the metrics can be
seen to pass and fail. No LLM, no database.
"""

from copilot.api import Answer, ToolCall
from evals.cases import load_cases

MODEL = "fake"

Q1_ANSWER = Answer(
    answer=(
        "**No, WELL-0001 is not producing oil.** The latest inspection, INS-0001-0203 on "
        "15 Oct 2026, was a drone inspection by Ryan Brooks. The wellhead was only 3.2 °C "
        "warmer than the air, below the T200 limit of 15 °C.\n\n"
        "Reason: note CTX-0001-003 by Jake Morales records a planned shut-in from 7 Oct for "
        "rod string replacement, expected back around 20 Oct. It is not yet in the "
        "maintenance system.\n\n"
        "The recorded status still says `active`, which is out of date."
    ),
    blocks=[{
        "type": "status_card",
        "title": "WELL-0001: not producing",
        "source": "r_fake",
        "fields": {},
        "rows": [{"asset_id": "WELL-0001", "is_producing": 0, "recorded_status": "active",
                  "inspection_id": "INS-0001-0203", "temp_delta_c": 3.2,
                  "producing_threshold_c": 15.0}],
    }],
    citations=["INS-0001-0203", "CTX-0001-003"],
    tool_calls=[
        ToolCall(name="well_status", args={"asset_ids": ["WELL-0001"]}, result_id="r_fake"),
        ToolCall(name="show_visual", args={"spec": {"type": "status_card", "source": "r_fake"}},
                 result_id=None),
    ],
    model=MODEL,
    error=None,
)

WRONG_ANSWER = Answer(answer="I could not find anything about that.", blocks=[], citations=[],
                      tool_calls=[], model=MODEL, error=None)


def _q1_question() -> str | None:
    return next((c.question for c in load_cases() if c.id == "Q1"), None)


def ask(question: str, user_id: str, thread_id: str | None = None) -> Answer:
    """Same signature as copilot.api.ask."""
    if question.strip() == (_q1_question() or "").strip():
        return Q1_ANSWER.model_copy(deep=True)
    return WRONG_ANSWER.model_copy(deep=True)
