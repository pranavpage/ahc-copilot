"""The ReAct agent: Gemma + the tools + the system prompt. Owner: D.

`graph` is the LangGraph Studio entry point (`langgraph.json`); the server adds persistence.
`get_graph()` is the in-process graph with an InMemorySaver, used by `copilot.api.ask`.
Thread: config["configurable"]["thread_id"]. User: config["configurable"]["user_id"] (in-process)
or the `x-user-id` request header (LangGraph server, sent by the web UI).
`remember` runs after each model call and indexes finished turns for `recall_conversations`.
"""

import inspect
import json
import os
import threading
import warnings
from functools import lru_cache, wraps

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from copilot import memory, results
from copilot.api import _text
from copilot.llm import get_llm
from copilot.prompt import build_system_prompt
from copilot.tools import ALL_TOOLS, ToolResult
from copilot.tools.visual import show_visual
from copilot.tools.wells import well_id

# create_react_agent moved to `langchain.agents` (not a dependency); the langgraph one still works.
warnings.filterwarnings("ignore", message="create_react_agent has been moved")

MODEL_ROWS = 50            # rows of a tool result sent to the model; the rest stay in the result store
RECURSION_LIMIT = 30

# Merge the system prompt into the first user message, for models that reject the system role.
MERGE_SYSTEM_PROMPT = os.getenv("MERGE_SYSTEM_PROMPT", "") == "1"


def _description(fn) -> str:
    """The docstring, without the 'Owner: …' line."""
    doc = inspect.getdoc(fn) or fn.__name__
    return "\n".join(line for line in doc.splitlines() if not line.startswith("Owner:")).strip()


def _dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _for_model(res: ToolResult) -> dict:
    """Compact view of a tool result: the first MODEL_ROWS rows and how many there are."""
    out = {"result_id": res.result_id, "row_count": len(res.rows), "rows": res.rows[:MODEL_ROWS],
           "ids": res.ids, "notes": list(res.notes), "truncated": res.truncated}
    if len(res.rows) > MODEL_ROWS:
        out["notes"].append(f"showing the first {MODEL_ROWS} of {len(res.rows)} rows; a visual of "
                            f"{res.result_id} shows all of them")
    return out


def _clean_well_args(kwargs: dict) -> list[str]:
    """Turn "0001", "well 1", … in `asset_id` / `asset_ids` into well IDs, in place. Returns notes."""
    notes = []

    def clean(value):
        a = well_id(value) if isinstance(value, str) else None
        if a and a != value:
            notes.append(f"'{value}' read as {a}")
        return a or value

    if kwargs.get("asset_id"):
        kwargs["asset_id"] = clean(kwargs["asset_id"])
    if kwargs.get("asset_ids"):
        kwargs["asset_ids"] = [clean(v) for v in kwargs["asset_ids"]]
    return notes


def data_tool(fn) -> StructuredTool:
    """Wrap a data tool. The model sees compact JSON; the artifact keeps result_id, ids and notes."""

    @wraps(fn)
    def run(**kwargs):
        try:
            id_notes = _clean_well_args(kwargs)
            res = fn(**kwargs)
            res = res if isinstance(res, ToolResult) else ToolResult.model_validate(res)
        except Exception as e:  # noqa: BLE001 - the model gets the error, the agent keeps going
            error = f"{fn.__name__} failed: {type(e).__name__}: {e}"
            return _dumps({"error": error}), {"result_id": None, "ids": [], "error": error}
        if not res.result_id:
            res.result_id = results.put(res.kind, res.rows)
        res.notes = id_notes + list(res.notes)
        artifact = {"result_id": res.result_id, "ids": res.ids, "notes": res.notes}
        return _dumps(_for_model(res)), artifact

    return StructuredTool.from_function(
        run, name=fn.__name__, description=_description(fn), response_format="content_and_artifact"
    )


def _show_visual(type: str, title: str, source: str, fields: dict) -> tuple[str, dict]:
    block = show_visual({"type": type, "title": title, "source": source, "fields": fields})
    if "error" in block:
        return _dumps(block), block
    summary = {k: block[k] for k in ("type", "title", "source", "fields")}
    return _dumps({**summary, "row_count": len(block["rows"]), "shown": True}), block


def visual_tool() -> StructuredTool:
    """show_visual with flat arguments (easier for Gemma than a nested spec). Validated in the tool,
    so an invalid spec comes back to the model as an error it can fix."""
    return StructuredTool.from_function(
        _show_visual,
        name="show_visual",
        description=(
            "Show one visual with the answer. `type`: status_card | table | line_chart | bar_chart | "
            "map | heatmap. `source`: the result_id of a data tool result. `fields`: the columns to use "
            "(see the system prompt). The rows are filled in from `source`."
        ),
        response_format="content_and_artifact",
    )


def _configurable(config: RunnableConfig | None) -> dict:
    """The run's configurable, with `user_id` filled from the `x-user-id` header on the LangGraph
    server (the server copies x-* request headers into configurable; the web UI sends it)."""
    c = dict((config or {}).get("configurable") or {})
    # The server also sets user_id = "" (its auth user, empty without auth), so the header wins.
    c["user_id"] = c.get("x-user-id") or c.get("user_id") or None
    return c


def recall_conversations(query: str | None = None, limit: int = 5, *, config: RunnableConfig) -> ToolResult:
    """The current user's earlier conversations, newest first (never another user's).

    Use it when the user refers to an earlier chat: "yesterday", "last time", "the wells we
    discussed". Each row is one conversation: its date, title and turns. Each turn has the
    question, the start of the answer, and the wells and other IDs that the answer named, in the
    order they were named (a "top 3" list keeps its order). `query`: optional words to match (well
    IDs, areas, topics). "Yesterday" means their most recent earlier conversation; the date does
    not have to match exactly. Say which conversation you used.
    """
    c = _configurable(config)
    user_id = c.get("user_id")
    if not memory.user_profile(user_id):
        return ToolResult(result_id="", kind="recall_conversations", rows=[], ids=[],
                          notes=["the user is not identified, so there are no earlier conversations"])
    rows = memory.recall(user_id, exclude_thread_id=c.get("thread_id"), query=query, limit=limit)
    notes = [] if rows else ["no earlier conversation with this user"
                             + (f" matches '{query}'" if query else "")]
    return ToolResult(result_id="", kind="recall_conversations", rows=rows, ids=[], notes=notes)


def build_tools() -> list[StructuredTool]:
    tools = [visual_tool() if fn is show_visual else data_tool(fn) for fn in ALL_TOOLS]
    return [*tools, data_tool(recall_conversations)]


def _turn_text(messages: list[AnyMessage]) -> tuple[str, str]:
    """(question, answer) of the latest turn: the last user message and the last AI text after it.
    Some models write the answer next to the show_visual call and end with an empty message."""
    start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=None)
    if start is None:
        return "", ""
    texts = [t for m in messages[start + 1:] if isinstance(m, AIMessage) and (t := _text(m)).strip()]
    return _text(messages[start]), texts[-1] if texts else ""


def remember(state, config: RunnableConfig) -> dict:
    """After each model call: when the turn is finished (no tool calls), index it for later chats."""
    messages = state["messages"]
    if not messages or not isinstance(messages[-1], AIMessage) or messages[-1].tool_calls:
        return {}
    c = _configurable(config)
    question, answer = _turn_text(messages)
    try:
        memory.remember(c.get("thread_id"), c.get("user_id"), question, answer)
    except Exception as e:  # noqa: BLE001 - memory must never break an answer
        warnings.warn(f"remember failed: {type(e).__name__}: {e}")
    return {}


def _prompt(state, config: RunnableConfig) -> list[AnyMessage]:
    """System prompt built at each model call, so it follows the current DB_PATH and user."""
    system = build_system_prompt(_configurable(config).get("user_id"))
    messages = list(state["messages"])
    if not MERGE_SYSTEM_PROMPT:
        return [SystemMessage(system), *messages]
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            messages[i] = HumanMessage(f"{system}\n\n---\n\n{m.content}", id=m.id)
            break
    return messages


def make_graph(model=None, checkpointer=None):
    """The ReAct agent. `model` defaults to get_llm() (MODEL with FALLBACK_MODEL)."""
    return create_react_agent(
        model if model is not None else get_llm(), build_tools(), prompt=_prompt,
        post_model_hook=remember, checkpointer=checkpointer,
    ).with_config(recursion_limit=RECURSION_LIMIT)


_graph_lock = threading.Lock()


@lru_cache
def _get_graph():
    return make_graph(checkpointer=InMemorySaver())


def get_graph():
    """In-process graph with an in-memory checkpointer (one per process). Locked, so threads
    that ask at the same time (parallel evals) share one graph and one conversation memory."""
    with _graph_lock:
        return _get_graph()


get_graph.cache_clear = _get_graph.cache_clear


graph = make_graph()
