# Evals: one result format

Every run uses the same statuses, records and table in the terminal, the run log
(`evals/runs/<run_id>.jsonl`), the reports (`evals/reports/<run_id>.md|.html`) and the history
(`evals/history.csv`), so any two runs can be compared. Code: `evals/schema.py` (rules),
`evals/runner.py` (log), `evals/report.py` (reports).

## Statuses

`PASS | FAIL | ERROR | SKIP`, the same words everywhere.

| | Metric | Case (checked in this order) |
|---|---|---|
| `ERROR` | the metric raised (e.g. judge API error) | `ask()` raised, `Answer.error` is set, or a dependency case errored |
| `FAIL` | score below threshold, or a forbidden item found | any metric is `FAIL` |
| `PASS` | `success` is true | everything else |
| `SKIP` | does not apply (no expected visual; Judge without `--judge`) | – |

- A metric `ERROR` on a case that is not `ERROR` sets `incomplete: true` on the case.
- **Case score:** mean score of the metrics that are not `SKIP` and not `ERROR` (0–1).
- **Pass rate:** PASS / (PASS + FAIL). Errors are reported separately ("7/10 pass · 2 fail · 1 error"):
  an error is an infrastructure problem, not a copilot quality problem.
- Dependency cases (run only because a selected case `follows` them) show as "(dep)" and are not counted.

## Metrics (`evals/metrics.py`)

| Metric | Version | Threshold | Score | `details` |
|---|---|---|---|---|
| `FactRecall` | 2 | 1.0 | share of `must_include` items found in answer + citations + blocks (a whole number matches with or without ".0"); any `must_not_include` → FAIL | `found`, `missing` (each with `in_tool_results` and `tools`), `forbidden` |
| `VisualMatch` | 1 | 1.0 | 1 if a block has the expected type; SKIP if `visual: none` | `expected`, `actual` |
| `Judge` (L1 data) | 3 | 1.0 | LLM judge (JUDGE_MODEL, default `deepseek/deepseek-v4-pro` on OpenRouter) on the answer text **and its visuals**: the rubric met and no contradiction (facts are FactRecall's job); extra justification is fine. Score = mean of [rubric met, no contradictions]. Only with `--judge` | `rubric_met`, `contradictions`, `evaluation_model` |

Records use deepeval `MetricData` names plus `status`, `version`, `details`. The report flags a
comparison against a baseline made with different metric versions.

## Failure categories

Each FAIL or ERROR case gets a list from this fixed set:

| Category | Rule |
|---|---|
| `error` | `ask()` raised, `Answer.error` is set (or a dependency errored) |
| `rate_limit` | an error text contains 429 or "rate limit" |
| `retrieval` | a missing item is in **no** tool result (wrong tool, arguments or data) |
| `generation` | a missing item **is** in a tool result but not in the answer |
| `forbidden` | a `must_not_include` item was found |
| `no_visual` | a visual was expected and the answer has no blocks |
| `wrong_visual` | blocks, but none of the expected type |
| `judge` | the Judge is FAIL |

The report's category counts, by count, are the list of what to fix next.

## Commands

```bash
uv run pytest evals                          # all cases, live (OpenRouter)
uv run pytest evals --cases Q2               # one case (--cases A1 = Q1–Q10, A2 = Q11–Q18)
uv run pytest evals --judge                  # also the LLM judge
uv run pytest evals --workers 1              # one case at a time (default 6 in parallel, env EVAL_WORKERS)
EVAL_ASK=evals.fake:ask uv run pytest evals  # offline, no LLM (Q1 PASS, Q10 ERROR, others FAIL)
uv run python -m evals.report                # report of the newest run (.md + .html)
uv run python -m evals.report RUN --baseline evals/baseline.json
uv run python -m evals.report --record       # + one row in evals/history.csv
uv run python -m evals.report --set-baseline # + evals/baseline.json from this run
REASONING=1 uv run pytest evals              # ask OpenRouter for Gemma's reasoning (shown in the HTML)
```

Cases run in two parts, on one temp copy of the database:

1. **Stateless cases** (one case, one turn: Q1–Q10, Q18) run in parallel, `--workers` at a time.
2. **Stateful chains** run one at a time: a case with more than one turn, or cases linked by
   `follows` (Q11 → Q16b, Q12a → Q12b → Q15a, Q13 → Q15b, Q14a → Q14b, Q16a, Q17a → Q17b). They
   write memory rows (and later corrections, notes and rules) that the next turn or case reads.
   The database is restored from a snapshot before part 2 and after each chain, so every chain
   starts from the original data and sees only its own writes.

Runner.serial decides which part a chain is in. Case lines in the run log are in finish order; reports
sort them by case ID.

`pytest evals` prints the results table, the pass line and the run log path, and writes the HTML
report. A FAIL test shows the failure block from the report; an ERROR test starts with `ERROR:`.

## Adding a metric

1. Subclass deepeval `BaseMetric` in `evals/metrics.py`: set a `version` class constant, a `threshold`,
   and in `measure()` set `score`, `success`, `reason` and a `details` dict (`skipped = True` for SKIP).
2. Add a `(case, judge) -> metric` factory to `METRICS` and its version to `METRIC_VERSIONS`.
3. Add its name to `METRIC_NAMES` in `evals/schema.py` (a table column), and a category if needed.
4. Bump `version` whenever the metric's logic changes.

## Baseline and history policy

- Commit `evals/history.csv`, `evals/baseline.json` and `evals/reports/<run_id>.md` for every run you
  `--record`. Run logs (`evals/runs/`) and HTML reports stay out of git (they hold row previews).
- Record live runs only (`copilot.api:ask`). Offline runs with `evals.fake` are for testing the tooling.
- Change the baseline only on purpose: after a run with no regressions, or with the reason in the
  commit message.
