"""Chat entry point. Owner: D."""

import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from copilot.config import get_settings


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


def _text(message: BaseMessage) -> str:
    """Message content as text (content can be a list of parts)."""
    if isinstance(message.content, str):
        return message.content
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in message.content)


def build_answer(turn: list[BaseMessage]) -> Answer:
    """Answer from the messages of one turn (the user message and everything after it)."""
    tool_messages = {m.tool_call_id: m for m in turn if isinstance(m, ToolMessage)}
    ai_messages = [m for m in turn if isinstance(m, AIMessage)]

    tool_calls, blocks, citations = [], [], {}
    for ai in ai_messages:
        for call in ai.tool_calls:
            reply = tool_messages.get(call["id"])
            artifact = reply.artifact if reply is not None and isinstance(reply.artifact, dict) else {}
            result_id = None
            if call["name"] == "show_visual":
                if artifact and "error" not in artifact:
                    blocks.append(artifact)
            else:
                result_id = artifact.get("result_id")
                citations.update(dict.fromkeys(artifact.get("ids", [])))
            tool_calls.append(ToolCall(name=call["name"], args=call["args"], result_id=result_id))

    # The answer is the last AI text of the turn: some models write it next to the show_visual
    # call and end with an empty message.
    texts = [t for t in map(_text, ai_messages) if t.strip()]
    final = ai_messages[-1] if ai_messages else None
    model = (final.response_metadata.get("model_name") if final else None) or get_settings().model
    return Answer(answer=texts[-1] if texts else "", blocks=blocks, citations=list(citations),
                  tool_calls=tool_calls, model=model, error=None)


def ask(question: str, user_id: str, thread_id: str | None = None) -> Answer:
    """Answer one message from user_id. Same thread_id = same conversation. Never raises."""
    from copilot.agent import get_graph     # imported here so `import copilot.api` stays light

    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex, "user_id": user_id}}
        before = len(graph.get_state(config).values.get("messages", []))
        state = graph.invoke({"messages": [HumanMessage(question)]}, config)
        return build_answer(state["messages"][before:])
    except Exception as e:  # noqa: BLE001 - the caller gets the error in the Answer
        return Answer(answer="", blocks=[], citations=[], tool_calls=[], model=get_settings().model,
                      error=f"{type(e).__name__}: {e}")
