"""Smoke test: does each model return a tool call? 1–2 OpenRouter requests per model, no retries.

    uv run python scripts/smoke_tool_call.py

For MODEL and FALLBACK_MODEL: one request with a system message. If the model rejects it (not
a rate limit), one more request with the system text merged into the user message.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from copilot.config import get_settings
from copilot.llm import chat_model

SYSTEM = "You answer questions about oil wells. Always use a tool for facts."
QUESTION = "Is WELL-0001 producing oil right now?"


@tool
def well_status(asset_id: str) -> str:
    """Current status of one well (producing yes/no, last inspection)."""
    return "{}"


def try_once(model: str, merge_system: bool) -> bool:
    """True if the request got an answer or was rate limited (no point in merging)."""
    if merge_system:
        messages = [HumanMessage(f"{SYSTEM}\n\n{QUESTION}")]
    else:
        messages = [SystemMessage(SYSTEM), HumanMessage(QUESTION)]
    label = f"{model} ({'system merged' if merge_system else 'system role'})"
    try:
        msg = chat_model(model, max_retries=0).bind_tools([well_status]).invoke(messages)
    except Exception as e:  # noqa: BLE001 - report every failure
        print(f"{label}: ERROR {type(e).__name__}: {e}")
        return getattr(e, "status_code", None) == 429
    answered_by = msg.response_metadata.get("model_name")
    if msg.tool_calls:
        calls = ", ".join(f"{c['name']}({c['args']})" for c in msg.tool_calls)
        print(f"{label}: TOOL CALL {calls} [answered by {answered_by}]")
    else:
        print(f"{label}: NO tool call; text={msg.content!r:.200} [answered by {answered_by}]")
    return True


def main() -> None:
    s = get_settings()
    for model in (s.model, s.fallback_model):
        if not try_once(model, merge_system=False):
            try_once(model, merge_system=True)


if __name__ == "__main__":
    main()
