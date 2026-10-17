# Copilot web UI

Next.js + assistant-ui chat for the LangGraph server (`langgraph.json`, graph `copilot`).
See the root README, "Chat in the browser".

- `app/MyRuntimeProvider.tsx`: the LangGraph runtime. `/api/*` is proxied to `LANGGRAPH_API_URL`.
- `app/toolkit.tsx`: tool UIs. `show_visual` renders its artifact (the spec + rows) with `components/visual/`.
- `components/visual/spec.ts`: finds the columns for each visual type. If the model sends no
  `x`/`y`/`value` keys, it uses the columns named in `fields`, then the row columns.
- `components/assistant-ui/elements/thread.aui.tsx`: from the assistant-ui template. One change:
  `show_visual` is not put in the collapsed tool group.
