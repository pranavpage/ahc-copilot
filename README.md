# Asset Intelligence Copilot

A chat copilot for a synthetic oil field (200 wells, 4 years of history). You ask a question in plain
English. A ReAct agent (Gemma on OpenRouter, LangGraph) calls typed data tools on a SQLite database,
writes the answer, cites record IDs and can show one visual (status card, table, chart, map, heatmap).

- `copilot/`: the agent (`agent.py`), `ask()` (`api.py`), the tools (`tools/`), the terminal chat (`chat.py`).
- `web/`: the chat UI. It renders `show_visual` blocks (`web/components/visual/`).
- `db/`: the schema and the loader. The loader builds `data/copilot.db` from the dataset.
- `evals/`: 18 eval questions (`cases.yaml`), the runner, the metrics and the reports. See [EVALS.md](EVALS.md).
- `PLAN.md`, `PLAN-UI.md`, `TASKS.md`: the plan and who owns which files.

## Quickstart

You need [uv](https://docs.astral.sh/uv/) and an [OpenRouter](https://openrouter.ai) API key.

```bash
# 1. The dataset. It is a gitlink with no .gitmodules, so clone it into its folder.
#    (Conductor workspaces do this in the setup script.)
git clone https://github.com/FlytBaseAILabs/flytbase-ahc-swe-asset-intelligence-dataset
git -C flytbase-ahc-swe-asset-intelligence-dataset checkout b8de8c9

# 2. Python packages
uv sync

# 3. Settings: set OPENROUTER_API_KEY. The ":free" model IDs are often rate limited (429);
#    the paid IDs cost very little:
#    MODEL=google/gemma-4-26b-a4b-it  FALLBACK_MODEL=google/gemma-4-31b-it
cp .env.example .env

# 4. The database (data/copilot.db). "Today" in the data is 2026-10-16.
uv run python db/load.py

# 5. Check: the unit tests use no LLM
uv run pytest tests
```

## Test the system manually

Do the steps in this order. Each step tests one more layer.

### 1. The data tools (no LLM)

```bash
uv run python -c "
from copilot.tools import well_status
r = well_status(asset_ids=['WELL-0001'])
print(r.ids, r.notes); print(r.rows[0])"
```

Expected: WELL-0001 is not producing (`is_producing: False`, `temp_delta_c: 3.2`), last inspection
INS-0001-0203 by Ryan Brooks, and note CTX-0001-003 (planned shut-in). The other tools are
`inspection_series`, `downtime`, `spills`, `well_records` and `search_docs` (see `TASKS.md`).

### 2. The model can call tools (1–2 requests per model)

```bash
uv run python scripts/smoke_tool_call.py
```

### 3. Chat in the terminal

```bash
uv run python -m copilot.chat --user U-201
```

Each answer prints the text, then `[visual]`, `[tool]` (name, arguments, result id), `[citations]` and
`[model]` lines. Commands: `/new` (new thread), `/user U-202` (change user, same thread), `/quit`.

Questions to try (the expected answers are in `evals/cases.yaml`):

| Question | Look for |
|---|---|
| Is WELL-0001 producing oil right now? When was it last inspected, and by whom? Show me its status card. | not producing, INS-0001-0203, Ryan Brooks, 3.2, CTX-0001-003, a status card |
| Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table. | WELL-0164, WELL-0170, WELL-0172, WELL-0175, a table |
| How many days was WELL-0001 down in 2025? | 21 days |
| How many oil spills has WELL-0001 had in the last 4 years, and how much oil in total? List them in a table. | 6 spills, 15.1 bbl, the rainwater correction |

### 4. Chat in the browser

The web UI (`web/`, Next.js + [assistant-ui](https://www.assistant-ui.com)) talks to the LangGraph
server. You need Node 20+. Run the two commands in two terminals:

```bash
uv run langgraph dev --no-browser --port 2024 --allow-blocking   # the agent API
cd web && cp .env.example .env.local && npm install && npm run dev -- -p 3000
```

Open http://localhost:3000. `--allow-blocking` is necessary: the tools use sync SQLite calls, and
without the flag every run fails with `BlockingError`. Each answer shows the text and the visual;
"N tool calls" opens the data tool calls. The thread list is on the left.

Users (`--user`): U-201 Michael Turner (production supervisor, the default), U-202 Jessica Reed
(inspector), U-102 Jake Morales (operator), U-301 Robert Hayes (maintenance lead), U-401 Laura Simmons
(HSE officer). All users: `sqlite3 data/copilot.db "select * from users"`.

### 4. LangGraph Studio (see each step of the agent)

```bash
uv run langgraph dev
```

Open the Studio URL that it prints. Select the `copilot` graph. Send a message with
`config.configurable.user_id = "U-201"`.

### 5. The evals

```bash
EVAL_ASK=evals.fake:ask uv run pytest evals   # offline: tests the eval tooling, no LLM
uv run pytest evals --cases Q1                # one live case (about 3 requests)
uv run pytest evals --cases A1                # Q1–Q10 live
uv run python -m evals.report                 # Markdown report of the newest run
open evals/reports/<run_id>.html              # the timeline of each case
```

The HTML report has one section per case: the metrics, the missing items (tagged `retrieval` or
`generation`), the user message, each model step with its tokens, each tool call with its arguments and
rows, the visuals, and the final answer with the expected items highlighted. Use the Failures and
Errors buttons to filter. To also see Gemma's reasoning, run with `REASONING=1`. Statuses, metrics,
failure categories and the baseline policy are in [EVALS.md](EVALS.md).

## Problems

| Problem | Fix |
|---|---|
| `data/copilot.db not found` | `uv run python db/load.py` |
| The loader finds no data | Clone the dataset (Quickstart step 1). |
| `429` / `rate limit` in answers | Use the paid model IDs in `.env`; the eval report marks these cases `ERROR` + `rate_limit`. |
| A model rejects the system message | `MERGE_SYSTEM_PROMPT=1` puts the system prompt in the first user message. |
