"""Chat entry point. Owner: D."""

from pydantic import BaseModel

from copilot.config import get_settings
from copilot.tools.base import STUB_NOTE


class ToolCall(BaseModel):
    name: str
    args: dict
    result_id: str | None      # set for data tools


class Answer(BaseModel):
    answer: str                # markdown text
    blocks: list[dict]         # filled visual blocks from show_visual
    citations: list[str]       # record IDs and doc sections used
    tool_calls: list[ToolCall]
    model: str                 # the model that answered (main or fallback)
    error: str | None


def ask(question: str, user_id: str, thread_id: str | None = None) -> Answer:
    """Answer one message from user_id. Same thread_id = same conversation.

    Owner: D.
    """
    return Answer(answer=STUB_NOTE, blocks=[], citations=[], tool_calls=[],
                  model=get_settings().model, error=STUB_NOTE)
