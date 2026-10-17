# Plan: fastest path to evals

Goal: run the example questions through a real agent and get a score, as early as possible.
Then improve by score. Memory and UI come after the first score.

Stack: Python 3.13 (uv) · LangGraph · Gemma 4 26B A4B on OpenRouter · SQLite (db/) · deepeval · Streamlit (later)

## Step 0. Environment (20 min)

1. `uv init` with Python 3.13. Add: `langgraph langchain-openai langgraph-checkpoint-sqlite deepeval pyyaml pytest python-dotenv`.
2. `.env`: `OPENROUTER_API_KEY`, `MODEL=google/gemma-4-26b-a4b-it:free`, `FALLBACK_MODEL=google/gemma-4-31b-it:free`.
3. **Buy $10 of OpenRouter credits.** Without credits the free limit is 50 requests/day. One eval run of
   10 questions × ~5 model calls = ~50 requests. With credits: 1,000/day.
4. Smoke test: one `ChatOpenAI(base_url="https://openrouter.ai/api/v1")` call with one bound tool.
   Confirm Gemma returns a tool call. If not, switch to the 31B model now, not later.

Done when: a tool call comes back from Gemma.

## Step 1. Eval cases (30 min) — write these BEFORE the agent

File: `evals/cases.yaml`. Start with A1 only (Q1–Q10, single turn). Add A2/B later.

```yaml
- id: Q2
  question: "Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table."
  visual: table
  must_include: [WELL-0164, WELL-0170, WELL-0172, WELL-0175, MNT-0170-031, MNT-0172-028]
  must_not_include: []
  rubric: "Says WELL-0164 and WELL-0175 have no recorded reason and suggests a check. Does not invent a cause."
```

- `must_include`: IDs, numbers, dates from the expected answer (e.g. `"21"`, `"15.1"`, `INS-0001-0203`).
- `visual`: card | table | line | bar | map | heatmap | none.
- `rubric`: only for what strings cannot check (honesty, conflicts, "no recorded reason").

Done when: 10 cases. The expected values are already verified against `data/copilot.db`.

## Step 2. Minimal agent (60–90 min)

File: `copilot/agent.py`. Use `create_react_agent` (prebuilt) with a system prompt and 7 tools.
Tools are typed wrappers over the SQL views that already give correct answers. Do not ask Gemma to write SQL yet.

| Tool | Backed by | Questions |
|---|---|---|
| `well_status(asset_ids?, area?, not_producing_only?)` | `well_status_now` + open repairs + valid notes | Q1, Q2 |
| `inspection_series(asset_id, start, end)` | `inspections_effective` | Q3 |
| `downtime(start, end, asset_id?, area?, top_n?)` | `inspections_effective` | Q5, Q6 |
| `spills(start?, end?, asset_id?, area?)` | `spills` | Q4, Q7, Q8, Q10 |
| `well_records(asset_id, start, end)` | maintenance, regulatory_events, notes, report_compliance | Q9 |
| `search_docs(query, asset_id?)` | `search_fts` + `rules` | citations for manuals/SOPs/reports |
| `show_visual(type, title, data)` | returns the spec; UI renders it later | all |

Rules for tools:
- Accept area by name ("Northeast Block 8") or ID. Resolve in the tool, not in the model.
- "today" comes from the `settings` table. Tools take explicit dates; the system prompt gives today's date.
- Every row returned carries its record IDs, so the model can cite them.
- Return compact JSON (Gemma context and rate limits).

File: `copilot/run.py` — `ask(question, user_id) -> {answer, visual, tool_calls}`. CLI for manual tests.

Done when: Q1 and Q2 give correct answers from the CLI.

## Step 3. Eval runner (45 min)

File: `evals/test_a1.py` (pytest + deepeval).

Metrics, cheapest first:
1. `FactRecall` (custom deepeval `BaseMetric`, no LLM): share of `must_include` strings in the answer
   + visual text. Threshold 1.0.
2. `VisualMatch` (custom, no LLM): `show_visual` type == case `visual`.
3. `GEval` with `rubric` (LLM judge via deepeval `OpenRouterModel`). Only on cases with a rubric.
   Off by default (`--judge` flag) to save requests.

Also:
- Save each run to `evals/runs/<timestamp>.jsonl` (question, answer, tool calls, scores), so a failing
  case can be debugged without a re-run.
- `pytest evals -k Q2` to run one case.

Done when: **first score for Q1–Q10.**

## Step 4. Improve by score (loop)

Fix the lowest cases first. Typical fixes: tool output shape, system prompt (date windows, "cite IDs",
"say 'no recorded reason' when nothing explains a stop"), tool descriptions.
Expect Q9 (rules broken) to be the last one to pass. It needs records + reports + SOPs together.

## After the first score (not on the path to evals)

5. **Memory + multi-turn evals (Q11–Q18).**
   - Episodic memory: LangGraph `SqliteStore`, namespace `("users", user_id, "episodes")`. Write the
     wells/areas each answer was about. Private per user by namespace.
   - Shared notes and claims: LangGraph store, namespace `("wells", asset_id, "notes")`.
   - **Corrections and user rules: keep in the SQL tables** (`corrections`, `rules`). They change
     calculations (downtime, producing, spill class) and the SQL views apply them automatically. In the
     LG store, every tool would have to apply them in Python before each aggregation.
   - Tools: `record_correction`, `add_note`, `set_rule`, `recall_conversations`.
   - Eval cases get `turns: [{user, message}]` and a fresh store per case.
6. **UI: Streamlit.** All Python, same process as the agent. `st.chat_message` for chat, a user picker in
   the sidebar. One render function per `show_visual` type: card = `st.metric` in a bordered container,
   table = `st.dataframe`, line/bar/heatmap = Plotly, map = Plotly `scatter_map` (no token needed).
7. Generalisation: a read-only `query_sql` fallback tool for questions that the typed tools do not cover.
   Load the test dataset with `python3 db/load.py --data <dir>` and run the evals again.
