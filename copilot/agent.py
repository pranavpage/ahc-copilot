"""The ReAct agent: Gemma + the tools + the system prompt. Owner: D.

`graph` is the LangGraph Studio entry point (`langgraph.json`); the server adds persistence.
`get_graph()` is the in-process graph with an InMemorySaver, used by `copilot.api.ask`.
Thread: config["configurable"]["thread_id"]. User: config["configurable"]["user_id"].
"""

import inspect
import json
import os
import warnings
from functools import lru_cache, wraps

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from copilot import results
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


def build_tools() -> list[StructuredTool]:
    return [visual_tool() if fn is show_visual else data_tool(fn) for fn in ALL_TOOLS]


def _prompt(state) -> list[AnyMessage]:
    """System prompt built at each model call, so it follows the current DB_PATH."""
    system = build_system_prompt()
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
        model if model is not None else get_llm(), build_tools(), prompt=_prompt, checkpointer=checkpointer
    ).with_config(recursion_limit=RECURSION_LIMIT)


@lru_cache
def get_graph():
    """In-process graph with an in-memory checkpointer (one per process)."""
    return make_graph(checkpointer=InMemorySaver())


graph = make_graph()
