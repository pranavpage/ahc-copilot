"""Basic chat UI for the copilot. Calls copilot.api.ask in-process (no server needed).

    uv run streamlit run ui/app.py
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from copilot.api import Answer, ask
from copilot.db import rows as db_rows

st.set_page_config(page_title="Asset Intelligence Copilot", layout="wide")


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v if isinstance(v, str) else v.get("field") for v in value if v]
    if isinstance(value, dict) and value.get("field"):
        return [value["field"]]
    return []


def _cell(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value


def render_status_card(block: dict, df: pd.DataFrame) -> None:
    row = block["rows"][0]
    with st.container(border=True):
        st.markdown(f"**{row.get('asset_id', '')}**")
        scalars = {k: v for k, v in row.items() if not isinstance(v, (list, dict)) and k != "asset_id"}
        cols = st.columns(4)
        for i, (k, v) in enumerate(scalars.items()):
            cols[i % 4].metric(k, "—" if v is None else str(v))


def render_block(block: dict) -> None:
    st.markdown(f"**{block['title']}**")
    if not block.get("rows"):
        st.caption("(no rows)")
        return
    df = pd.DataFrame([{k: _cell(v) for k, v in r.items()} for r in block["rows"]])
    f, kind = block.get("fields", {}), block["type"]
    try:
        if kind == "status_card":
            render_status_card(block, df)
        elif kind == "table":
            cols = [c for c in _as_list(f.get("columns")) if c in df.columns]
            st.dataframe(df[cols] if cols else df, hide_index=True, width="stretch")
        elif kind == "line_chart":
            fig = px.line(df, x=_as_list(f["x"])[0], y=_as_list(f["y"]), markers=True)
            fig.update_layout(yaxis_title=f.get("unit"))
            st.plotly_chart(fig, width="stretch")
        elif kind == "bar_chart":
            fig = px.bar(df, x=_as_list(f["category"])[0], y=_as_list(f["value"])[0])
            fig.update_layout(yaxis_title=f.get("unit"))
            st.plotly_chart(fig, width="stretch")
        elif kind == "map":
            label = _as_list(f.get("label"))
            fig = px.scatter_map(df, lat=_as_list(f["lat"])[0], lon=_as_list(f["lon"])[0],
                                 hover_name=label[0] if label else None, zoom=8, height=450)
            fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width="stretch")
        elif kind == "heatmap":
            x, y, v = (_as_list(f[k])[0] for k in ("x", "y", "value"))
            pivot = df.pivot_table(index=y, columns=x, values=v, aggfunc="sum")
            st.plotly_chart(px.imshow(pivot, aspect="auto", text_auto=True), width="stretch")
        else:
            st.dataframe(df, hide_index=True, width="stretch")
    except Exception as e:  # noqa: BLE001 - a bad spec still shows the data
        st.caption(f"Could not draw {kind} ({type(e).__name__}: {e}); showing the rows.")
        st.dataframe(df, hide_index=True, width="stretch")


def render_answer(a: Answer) -> None:
    if a.error:
        st.error(a.error)
    st.markdown(a.answer or "_(no answer)_")
    for block in a.blocks:
        render_block(block)
    if a.citations:
        st.caption("Sources: " + ", ".join(a.citations))
    with st.expander(f"How I got this ({len(a.tool_calls)} tool calls, {a.model})"):
        for c in a.tool_calls:
            rid = f" → `{c.result_id}`" if c.result_id else ""
            st.markdown(f"- `{c.name}({json.dumps(c.args, ensure_ascii=False)})`{rid}")


@st.cache_data
def load_users() -> list[dict]:
    return db_rows("select user_id, name, role from users order by user_id")


# Sidebar: user and thread
users = load_users()
labels = {u["user_id"]: f"{u['user_id']} · {u['name']} ({u['role']})" for u in users}
ids = list(labels)
with st.sidebar:
    st.header("Copilot")
    user_id = st.selectbox("User", ids, index=ids.index("U-201") if "U-201" in ids else 0,
                           format_func=labels.get)
    if st.button("New chat", width="stretch") or "thread_id" not in st.session_state:
        st.session_state.thread_id = uuid.uuid4().hex
        st.session_state.messages = []
    st.caption(f"Thread {st.session_state.thread_id[:8]}")

# Chat
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        if m["role"] == "user":
            st.markdown(m["content"])
        else:
            render_answer(m["content"])

if question := st.chat_input("Ask about the wells…"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            answer = ask(question, user_id, st.session_state.thread_id)
        render_answer(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
