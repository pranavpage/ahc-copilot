# Plan addendum: frontend and generative UI

Addendum to `PLAN.md`, step 7. Start this after the first eval score.

Goal: the copilot answers in the chat with the right visual. The model composes the answer from a
**small, fixed catalog of components**. It does not write UI code, and it cannot invent a component.

## 1. Principles

1. **One catalog, defined in Python.** Each component is a Pydantic model. The same models give:
   the `show_visual` tool schema, the catalog text in the system prompt, the validation, and the JSON
   Schema for any frontend. Adding a component = 1 model + 1 renderer + 1 example spec.
2. **Data by reference, not by value.** Each data tool stores its rows under a `result_id` and returns
   that ID to the model. A visual spec names the `result_id` and the columns to use. The server fills
   in the rows. The model never types the numbers, so the chart always matches the database, and the
   model uses fewer tokens (a heatmap or 13-point line chart costs ~50 tokens, not ~1,000).
3. **Validate, repair, fall back.** An invalid spec returns the validation error to the model as the
   tool result, and the model tries again (max 1 retry). If it fails again, show the referenced rows as
   a table. The user never sees a broken visual.
4. **The renderer is replaceable.** The spec is plain JSON. Streamlit renders it first. A React
   renderer can use the same specs later, with no change to the agent.
5. **Trust is visible.** Every answer shows its evidence. Conflicts and corrections have their own
   components, not only text.

## 2. The catalog (9 components)

### Visuals (choose one per answer, or none)

| `type` | Use for | Spec fields (data from `source` = a `result_id`) |
|---|---|---|
| `status_card` | One well right now | `source`, `asset_id`. Shows: producing yes/no, °C above air vs. threshold, last inspection (ID, date, by, method), recorded status + "out of date" flag, reason |
| `table` | A list of wells, events, repairs | `source`, `columns: [{field, label, format: text\|number\|date\|id\|badge}]`, `highlight_where?` |
| `line_chart` | A value over time | `source`, `x`, `y: [field]`, `unit`, `mark_where?` (e.g. not producing), `threshold_line?` |
| `bar_chart` | Compare a few wells or areas | `source`, `category`, `value`, `unit`, `sort: desc\|asc\|none` |
| `map` | Where things are | `source`, `lat`, `lon`, `label`, `color_by?`, `popup: [field]` |
| `heatmap` | Two dimensions (area × month) | `source`, `x`, `y`, `value`, `unit`, `totals: bool` |

### Trust components (add to any answer)

| `type` | Use for | Spec fields |
|---|---|---|
| `evidence` | Every answer: the records and documents used | `items: [{id, kind: inspection\|repair\|report\|event\|note\|rule\|correction, label}]`. Click an item to see the record or the document section. |
| `conflict` | Users disagree with each other or with the data (Q12, Q17, Q18) | `subject`, `data_says: {statement, source_id}`, `claims: [{user, when, statement, source_id, status: confirmed\|unconfirmed}]`, `verdict` |
| `correction_receipt` | After feedback (Q12, Q13, Q14) | `target`, `field`, `old → new`, `by`, `reason`, `scope: record\|well\|well_type`, `effects: [text]` |

Optional, only if time remains: `evidence_images` for one inspection. The dataset gives image paths
but no files, so show labeled placeholders (RGB, thermal). The judges score how the copilot uses images,
not what is in them.

### Choosing the visual

The system prompt gives the table from the example questions: one well now → `status_card`, list →
`table`, over time → `line_chart`, compare → `bar_chart`, where → `map`, two dimensions → `heatmap`.
If the user names a visual, use it. The eval metric `VisualMatch` checks this.

## 3. Files

```
copilot/ui_catalog.py   Pydantic models (discriminated union on `type`) + catalog_prompt()
copilot/results.py      result store: result_id -> rows (per conversation, in memory + SQLite)
copilot/ui_resolve.py   spec + result store -> filled block (JSON), or a validation error
ui/render.py            one Streamlit function per `type`
ui/app.py               the chat app
ui/gallery.py           renders every example spec, no LLM calls
ui/fixtures/*.json      one example spec + rows per component
```

## 4. Steps

### UI-0. Catalog and gallery (45 min)

- Write the 9 Pydantic models and `catalog_prompt()`.
- Write one fixture per component, from the real expected answers: Q1 card, Q2 table, Q3 line,
  Q6 bar, Q7 map, Q8 heatmap, Q18 conflict, Q13 correction receipt.
- `ui/gallery.py`: `streamlit run ui/gallery.py` shows all of them. Build the renderers here, with no
  agent and no OpenRouter requests.
- Renderers: card = `st.container(border=True)` + `st.metric`; table = `st.dataframe`;
  line/bar/heatmap = Plotly; map = Plotly `scatter_map` (OpenStreetMap tiles, no token).

Done when: the gallery shows all 9 components correctly.

### UI-1. Connect the agent (45 min)

- Change `show_visual` to take a catalog spec. Data tools return `result_id`s.
- Add the evals: `CatalogValid` (all blocks validate; no LLM) next to `VisualMatch`.
- `ui/app.py`:
  - Sidebar: user picker (from the `users` table), "New chat", this user's past chats only.
  - Main: chat. Each answer = text (streamed) → visual block → trust components.
  - Expander "How I got this": the tool calls with their arguments. This helps the demo and the
    system-design discussion.

Done when: Q1, Q2, Q3, Q6, Q7 and Q8 show the correct visual from the chat.

### UI-2. Trust and feedback (30 min, with memory step 6)

- `conflict` and `correction_receipt` from the feedback tools (`record_correction`, `add_note`,
  `set_rule`).
- Buttons on `conflict`: "Confirm" / "Not correct". They send a normal chat message, so the agent
  handles them like typed text.

Done when: Q12, Q17 and Q18 show their components.

### UI-3. Optional: React renderer (exploration)

Go only if the evals reach the target and more than 2 hours remain before the test data release.

- Run the agent with `langgraph dev`. The frontend uses `useStream` from `@langchain/langgraph-sdk/react`.
- Use LangGraph generative UI: the `show_visual` node calls `push_ui_message(type, filled_spec)` from
  `langgraph.graph.ui`. The frontend maps each `type` to a React component.
- Same catalog, same specs. Generate TypeScript types from the Pydantic JSON Schema.
- Components: Recharts (line, bar), ECharts or a CSS grid (heatmap), MapLibre or Leaflet (map),
  TanStack Table (table).
- Keep Streamlit working. Switch the demo to React only when it renders all 9 gallery fixtures.

## 5. Risks

| Risk | Action |
|---|---|
| Gemma writes invalid specs | Small catalog, short field names, examples in the prompt, 1 retry, table fallback |
| Gemma puts numbers in the spec | Specs have no data fields, only `source` + column names |
| Wrong visual type | `VisualMatch` eval; the prompt table; the user's request has priority |
| Too much UI time | UI-0 and UI-1 only. UI-3 is optional and has a go/no-go rule |
