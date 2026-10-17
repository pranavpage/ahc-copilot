# First eval score: Q1–Q10

Run log: `evals/runs/20261017T075131Z.jsonl` (`uv run pytest evals --cases A1`, no `--judge`).
Model: `google/gemma-4-26b-a4b-it` for every case; the fallback model was never used. There were no 429s
and no errors. Wall time: 67 s.

The `:free` model IDs (the defaults in `copilot/config.py`) were rate-limited upstream on 17 Oct, so this
run set `MODEL=google/gemma-4-26b-a4b-it FALLBACK_MODEL=google/gemma-4-31b-it` in the environment.

**Score: 3 / 10 cases pass.** Mean FactRecall 0.80. VisualMatch 8 / 10.

## Summary

| case | FactRecall | VisualMatch | tool calls | seconds | model |
|---|---|---|---|---|---|
| Q1 | 1.00 pass | 1.00 pass | 2 | 4.9 | gemma-4-26b-a4b-it |
| Q2 | 0.91 FAIL | 1.00 pass | 2 | 10.6 | gemma-4-26b-a4b-it |
| Q3 | 0.75 FAIL | 1.00 pass | 2 | 4.1 | gemma-4-26b-a4b-it |
| Q4 | 1.00 pass | 0.00 FAIL | 1 | 6.0 | gemma-4-26b-a4b-it |
| Q5 | 0.44 FAIL | 1.00 pass | 2 | 4.9 | gemma-4-26b-a4b-it |
| Q6 | 0.60 FAIL | 1.00 pass | 3 | 7.1 | gemma-4-26b-a4b-it |
| Q7 | 1.00 pass | 1.00 pass | 2 | 7.7 | gemma-4-26b-a4b-it |
| Q8 | 0.50 FAIL | 1.00 pass | 2 | 6.2 | gemma-4-26b-a4b-it |
| Q9 | 0.77 FAIL | 0.00 FAIL | 1 | 7.6 | gemma-4-26b-a4b-it |
| Q10 | 1.00 pass | 1.00 pass | 2 | 7.3 | gemma-4-26b-a4b-it |

## Failed cases

- **Q2**: missing `2026-10-15`. Cause: **tool data wrong**. The block has the date only as the timestamp
  `inspected_at: "2026-10-15T11:45:00Z"`, which FactRecall does not match, and the answer does not give the
  date. Calls: `well_status(area="NE-08", not_producing_only=true)`, `show_visual(table, r_d25d)`.
- **Q3**: missing `2026-07-23`. Cause: **wrong arguments (dates)**. The model asked for 13 weeks but set
  `start=2026-07-24`, which is 12 weeks back, so it got 12 points instead of 13. Calls:
  `inspection_series(WELL-0001, 2026-07-24, 2026-10-16)`, `show_visual(line_chart, r_3279)`.
- **Q4**: all facts found, but there is no visual. Cause: **no `show_visual`**. The model wrote
  `show_visual(type="table", …)` as text at the end of the answer instead of calling the tool. Calls:
  `spills(asset_id=WELL-0001, 2022-10-16, 2026-10-16)`.
- **Q5**: missing `51.6`, `43.1`, `8.5`, `MNT-0001-021`, `MNT-0001-023`. Cause: **tool data wrong**.
  `downtime` returns the down dates and inspection IDs, but not the temperatures (needed to explain the
  24 Jul near-miss) or the linked maintenance records. The model did not call `inspection_series` or
  `well_records` to get them either. Calls: `downtime(WELL-0001, 2025-01-01, 2025-12-31)`,
  `show_visual(table, r_3d27)`.
- **Q6**: missing `49`, `42`. Cause: **tool data wrong**. `downtime_days` is a float, so the answer and
  block say `49.0` and `42.0`, and FactRecall does not match `49.0` to `49`. The wells and the ranking are
  correct. Calls: `downtime(area="Northeast Block 7 (NE-07)", …)`, which returned an unknown-area note, then
  `downtime(area="Northeast Block 7", 2026-06-16, 2026-10-16, top_n=3)`, `show_visual(bar_chart, r_8057)`.
- **Q8**: missing `35`, `43`, `37`, `26` (the 2026 spill count for each area). Cause: **tool data wrong**.
  `spills` returns 141 spill rows with no per-area totals, and the model only sees the first 50
  (`MODEL_ROWS`), so it cannot count them. The heatmap is correct, but it only has monthly cells. The
  answer gives no numbers and does not name Southwest Block 24 as the area with the most spills. Calls:
  `spills(2026-01-01, 2026-12-31, group_by=[area, month])` (`group_by` is not a parameter and was dropped),
  `show_visual(heatmap, r_16e8)`.
- **Q9**: missing `5000`, `6.8`, `2026-08-10`, and there is no visual. Cause: **no `show_visual`**. The
  four breaches and the REG IDs are correct, but the model made no visual call. It also left out the open
  $5,000 fine, the 6.8 bbl volume and the SR-03 due date, although all three are in the `well_records`
  rows. Calls: `well_records(WELL-0001, 2025-10-16, 2026-10-16)`.

These cases passed but have problems:

- **Q10**: `show_visual` `fields` were malformed: the keys were JSON fragments like `'{"asset_id"'`. The
  case passed because the rows come from `source`.
- **Q4, Q6, Q8**: the answer text ends with a `show_visual(...)` line written as text. In Q6 and Q8 the
  model also made the real call.

## Top 3 fixes

I checked these by re-scoring the logged answers with each change applied, with no new LLM calls.

1. **Whole-number floats as ints, and dates as `YYYY-MM-DD`, in tool rows** (`downtime_days` 49.0 → 49,
   `fine_usd` 5000.0 → 5000, and an `inspected_date` next to `inspected_at`). This could also be done in
   FactRecall instead, by accepting a trailing `.0` or a `T…` time. **Fixes Q2 and Q6**, and is half of
   the Q9 fix.
2. **Make the model call `show_visual` and never write it as text.** Add a prompt rule ("call
   show_visual; do not write it in the answer"), and/or have `ask()` reject or strip a text-only
   `show_visual(...)`. **Fixes Q4. With fix 1, also fixes Q9**: a table of `r_0a73` brings in 6.8 and
   2026-08-10, and fix 1 brings in 5000.
3. **Better aggregates from tools** (tie: one case each):
   - `spills` returns per-area totals, or a summary note when there are more than `MODEL_ROWS` rows
     (fixes **Q8**).
   - `downtime` returns the wellhead/air/delta reading and linked maintenance IDs for each down date
     (fixes **Q5**).
   - A computed window in the prompt or the tools ("last N weeks" → start date) fixes the date
     arithmetic (fixes **Q3**).

Fixes 1 and 2 together would take the score from 3/10 to 7/10.
