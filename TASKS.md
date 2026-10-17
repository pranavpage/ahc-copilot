# Tasks and file ownership

Step 1 (scaffold) defines the contracts below. A1, A2, B, C and D start in parallel from it.
F and G start after the first eval score (`PLAN.md` step 5, `PLAN-UI.md`).

**Only D calls OpenRouter. Parallel tasks must not edit files they do not own, or `pyproject.toml`.**
To change a shared contract file, ask its owner in the PR; do not edit it in your branch.

| Task | What | Owns (may edit) |
|---|---|---|
| Step 1 | Scaffold and contracts (done) | `pyproject.toml`, `uv.lock`, `.env.example`, `copilot/config.py`, `copilot/db.py`, `copilot/results.py`, `copilot/tools/base.py`, `copilot/tools/__init__.py`, `evals/cases.py`, `tests/test_contracts.py`, `TASKS.md` |
| A1 | Data tools: status | `copilot/tools/status.py`, `tests/test_status.py` |
| A2 | Data tools: records and docs | `copilot/tools/records.py`, `tests/test_records.py` |
| B | Eval cases Q1–Q10 (later Q11–Q18) | `evals/cases.yaml` |
| C | Eval runner and metrics (`FactRecall`, `VisualMatch`, `GEval` behind `--judge`) | `evals/test_cases.py`, `evals/metrics.py`, `evals/conftest.py`, `evals/runs/` |
| D | Agent and chat endpoint | `copilot/agent.py`, `copilot/api.py`, `copilot/prompt.py`, `copilot/tools/visual.py`, `copilot/run.py`, `langgraph.json` |
| F | New data in one command (`PLAN.md` step 5) | `db/load.py`, `db/schema.sql`, `evals/fixtures/`, `evals/test_data_change.py` |
| G | Generative UI (`PLAN-UI.md`) | `copilot/ui_catalog.py`, `copilot/ui_resolve.py`, `ui/`; takes over `copilot/tools/visual.py` from D (replaces `VisualSpec` with the catalog) |

## Contracts

- `copilot.config.get_settings()` → `Settings(openrouter_api_key, model, fallback_model, db_path)` from `.env`.
- `copilot.db`: `connect(read_only=True)` (URI `mode=ro`, `sqlite3.Row`), `rows(sql, params) -> list[dict]`,
  `today() -> str` from `settings.today`.
- `copilot.results`: `put(kind, rows) -> result_id` (e.g. `r_3f9a`), `get(result_id) -> rows`, `clear()`.
  In memory.
- Every data tool returns `ToolResult(result_id, kind, rows, ids, notes, truncated=False)`:
  - `kind` = the tool name; the rows are also stored under `result_id` with `results.put`.
  - `ids`: record IDs for citations (INS-…, MNT-…, REG-…, CTX-…, COR-…, doc sections).
  - `notes`: warnings, e.g. "no rule found", "unknown area; valid: …".
- Tools (`copilot.tools.ALL_TOOLS`, in this order):

  | Tool | Signature | Owner |
  |---|---|---|
  | `well_status` | `(asset_ids: list[str] \| None = None, area: str \| None = None, not_producing_only: bool = False)` | A1 |
  | `inspection_series` | `(asset_id: str, start: str, end: str)` | A1 |
  | `downtime` | `(start: str, end: str, asset_id: str \| None = None, area: str \| None = None, top_n: int \| None = None)` | A1 |
  | `spills` | `(start: str \| None = None, end: str \| None = None, asset_id: str \| None = None, area: str \| None = None)` | A2 |
  | `well_records` | `(asset_id: str, start: str, end: str)` | A2 |
  | `search_docs` | `(query: str, asset_id: str \| None = None, limit: int = 5)` | A2 |
  | `show_visual` | `(spec: VisualSpec) -> dict`; `VisualSpec(type, title, source, fields)` | D, then G |

- Tool rules:
  - Dates are `YYYY-MM-DD`; ranges are inclusive.
  - `area` accepts a name ("Northeast Block 8") or an ID ("NE-08"). Resolve it in the tool.
  - No data values in code (well IDs, area names, well types, thresholds, dates). Thresholds come from
    `well_rules`; names from `areas` / `wells`. An unknown value returns the valid values in `notes`.
  - Tools never raise for bad input: they return `rows=[]` and a note.
  - Docstrings are the tool descriptions the model sees. Keep them short and accurate.
- `copilot.api.ask(question, user_id, thread_id=None) -> Answer(answer, blocks, citations, tool_calls, model, error)`;
  `ToolCall(name, args, result_id)`.
- `evals.cases.load_cases(path="evals/cases.yaml") -> list[EvalCase]`. `EvalCase`: `id`, exactly one of
  `question` / `turns: [Turn(user_id, message)]`, `user_id="U-201"`, `visual` (a `VisualType`, `"none"` or
  null), `must_include`, `must_not_include`, `rubric`, `follows`.
- "Today" is `db.today()` (`2026-10-16` in the sample data), never `date.today()`.

## Commands

```bash
uv sync
uv run python db/load.py     # builds data/copilot.db
uv run pytest                # tests/ (contracts) + evals/
```

`tests/test_contracts.py` must pass on every branch.
