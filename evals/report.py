"""Report for one eval run: Markdown (terminal + evals/reports/<run_id>.md) and HTML.

    uv run python -m evals.report [RUN] [--baseline PATH] [--record] [--set-baseline]

RUN is a run log path or run id (default: the newest log in evals/runs/). The HTML report
(evals/reports/<run_id>.html, not in git) has the full timeline of each case.
`table()` and `failure_block()` are also used by the pytest summary (evals/conftest.py).
"""

import argparse
import csv
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.schema import METRIC_NAMES, Status, case_order, pass_line, summarize

EVALS = Path(__file__).resolve().parent
RUNS_DIR = EVALS / "runs"
REPORTS_DIR = EVALS / "reports"
HISTORY = EVALS / "history.csv"
BASELINE = EVALS / "baseline.json"
HISTORY_COLUMNS = ["run_id", "date", "sha", "dirty", "model", "cases", "pass", "fail", "error",
                   "pass_rate", "mean_fact_recall", "mean_visual", "mean_judge", "seconds"]
SCORE_CHANGE = 0.1         # score changes larger than this are listed against the baseline
ANSWER_CHARS = 300         # answer text in a failure block


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

@dataclass
class Run:
    path: Path
    start: dict
    cases: list[dict]
    end: dict | None

    @property
    def complete(self) -> bool:
        return self.end is not None

    @property
    def run_id(self) -> str:
        return self.start.get("run_id") or self.path.stem

    @property
    def summary(self) -> dict:
        """run_end, or the same totals computed from the finished cases."""
        return self.end or summarize(self.cases)


def load_run(path: Path) -> Run:
    start, cases, end = {}, [], None
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:     # a line cut by a crash
            continue
        kind = rec.get("type")
        if kind == "run_start":
            start = rec
        elif kind == "case":
            cases.append(rec)
        elif kind == "run_end":
            end = rec
    cases.sort(key=lambda c: case_order(c.get("case_id", "")))   # parallel runs log in finish order
    return Run(Path(path), start, cases, end)


def find_run(arg: str | None) -> Path:
    """A path, a run id, or (None) the newest log in evals/runs/."""
    if arg:
        p = Path(arg)
        if p.exists():
            return p
        p = RUNS_DIR / f"{arg.removesuffix('.jsonl')}.jsonl"
        if p.exists():
            return p
        raise SystemExit(f"run not found: {arg}")
    logs = sorted(RUNS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not logs:
        raise SystemExit(f"no run logs in {RUNS_DIR}. Run: uv run pytest evals")
    return logs[-1]


def load_baseline(path: Path | None = BASELINE) -> dict | None:
    return json.loads(path.read_text()) if path and path.exists() else None


# ---------------------------------------------------------------------------
# Shared pieces (terminal, Markdown, HTML)
# ---------------------------------------------------------------------------

def fmt_score(score: float | None) -> str:
    return "-" if score is None else f"{score:.2f}"


def metric_cell(m: dict | None) -> str:
    """`0.75 FAIL`, `1.00 PASS`, `SKIP`, `ERROR`."""
    if m is None:
        return "-"
    if m["status"] in (Status.SKIP, Status.ERROR):
        return m["status"]
    return f"{fmt_score(m['score'])} {m['status']}"


def metric(case: dict, name: str) -> dict | None:
    return next((m for m in case["metrics"] if m["name"] == name), None)


def case_label(case: dict) -> str:
    return case["case_id"] + (" (dep)" if case.get("as_dependency") else "")


def vs_baseline(case: dict, baseline: dict | None) -> str:
    """`FAIL → PASS`, `+0.25`, `=`, `new`; empty without a baseline."""
    if not baseline:
        return ""
    old = baseline["cases"].get(case["case_id"])
    if old is None:
        return "new"
    if old["status"] != case["status"]:
        return f"{old['status']} → {case['status']}"
    if old.get("score") is None or case.get("score") is None:
        return "="
    delta = case["score"] - old["score"]
    return "=" if abs(delta) < 0.005 else f"{delta:+.2f}"


def changes(cases: list[dict], baseline: dict | None) -> dict:
    """Regressions (PASS → FAIL/ERROR), fixes (FAIL/ERROR → PASS) and score changes > 0.1."""
    out = {"regressions": [], "fixes": [], "score_changes": []}
    if not baseline:
        return out
    for c in cases:
        if c.get("as_dependency"):
            continue
        old = baseline["cases"].get(c["case_id"])
        if old is None:
            continue
        if old["status"] == Status.PASS and c["status"] != Status.PASS:
            out["regressions"].append((c["case_id"], old["status"], c["status"]))
        elif old["status"] != Status.PASS and c["status"] == Status.PASS:
            out["fixes"].append((c["case_id"], old["status"], c["status"]))
        if old.get("score") is not None and c.get("score") is not None \
                and abs(c["score"] - old["score"]) > SCORE_CHANGE:
            out["score_changes"].append((c["case_id"], old["score"], c["score"]))
    return out


def table_rows(cases: list[dict], baseline: dict | None) -> list[list[str]]:
    rows = []
    for c in cases:
        status = c["status"] + (" (incomplete)" if c.get("incomplete") else "")
        rows.append([case_label(c), status, fmt_score(c.get("score")),
                     *(metric_cell(metric(c, n)) for n in METRIC_NAMES),
                     ", ".join(c.get("categories") or []), vs_baseline(c, baseline),
                     f"{c.get('seconds') or 0:.1f}"])
    return rows


TABLE_HEADER = ["case", "status", "score", *METRIC_NAMES, "categories", "vs baseline", "s"]


def table(cases: list[dict], baseline: dict | None = None) -> str:
    """The results table, as Markdown. The one table for the terminal and the reports."""
    def md(cell: str) -> str:
        return str(cell).replace("|", "\\|")
    lines = ["| " + " | ".join(TABLE_HEADER) + " |", "|" + "---|" * len(TABLE_HEADER)]
    lines += ["| " + " | ".join(md(c) for c in row) + " |" for row in table_rows(cases, baseline)]
    return "\n".join(lines)


def _last_lines(text: str, n: int = 3) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[-n:]) if len(lines) > n else "\n".join(lines)


def _args(args: dict) -> str:
    return json.dumps(args, ensure_ascii=False, default=str)


def failure_block(case: dict) -> str:
    """Why a FAIL/ERROR case failed: metric reasons, missing items, tool calls, the answer."""
    head = [case["case_id"], case["status"], f"score {fmt_score(case.get('score'))}"]
    if case.get("categories"):
        head.append(", ".join(case["categories"]))
    lines = [" · ".join(head)]
    for err in case.get("errors") or ([case["error"]] if case.get("error") else []):
        lines.append("  error: " + _last_lines(err).replace("\n", "\n    "))
    for m in case["metrics"]:
        if m["status"] not in (Status.FAIL, Status.ERROR):
            continue
        reason = str(m.get("reason") or m.get("error"))
        reason = reason if len(reason) <= 200 else reason[:200] + "…"
        lines.append(f"  {m['name']}: {metric_cell(m)}: {reason}")
        for item in m["details"].get("missing", []):
            where = "generation" if item["in_tool_results"] else "retrieval"
            tools = f" (in {', '.join(item['tools'])})" if item["tools"] else ""
            lines.append(f"    - {item['item']} [{where}]{tools}")
        for item in m["details"].get("forbidden", []):
            lines.append(f"    - {item} [forbidden]")
    n_turns = len(case.get("answers") or [])
    calls = case.get("tool_calls") or []
    if calls:
        lines.append("  tool calls:")
        for c in calls:
            turn = f"turn {c['turn'] + 1}: " if n_turns > 1 else ""
            n = c.get("row_count")
            rows = "" if n is None else f", {n} row{'' if n == 1 else 's'}"
            result = f" -> {c['result_id']}{rows}" if c.get("result_id") else ""
            lines.append(f"    - {turn}{c['name']}({_args(c['args'])}){result}")
    elif case.get("answers"):
        lines.append("  tool calls: none")
    answer = (case["answers"][-1].get("answer") or "") if case.get("answers") else ""
    if answer:
        short = answer[:ANSWER_CHARS] + ("…" if len(answer) > ANSWER_CHARS else "")
        lines.append("  answer: " + short.replace("\n", "\n    "))
    return "\n".join(lines)


def models(run: Run) -> str:
    used = sorted({c["model"] for c in run.cases if c.get("model")})
    configured = run.start.get("model")
    out = f"{configured} (fallback {run.start.get('fallback_model')})" if configured else "?"
    extra = [m for m in used if m != configured and not (configured or "").startswith(m)]
    return out + (f"; answered by {', '.join(used)}" if extra else "")


def version_warnings(run: Run, baseline: dict | None) -> list[str]:
    if not baseline:
        return []
    old, new = baseline.get("metric_versions") or {}, run.start.get("metric_versions") or {}
    return [f"{n} v{old.get(n)} → v{new.get(n)}" for n in sorted(set(old) | set(new))
            if old.get(n) != new.get(n)]


def baseline_line(run: Run, baseline: dict | None) -> str | None:
    if not baseline:
        return None
    ch = changes(run.cases, baseline)
    old = {s: sum(1 for c in baseline["cases"].values() if c["status"] == s)
           for s in (Status.PASS, Status.FAIL, Status.ERROR)}
    return (f"vs baseline {baseline['run_id']}: {pass_line(old)} → {pass_line(run.summary['totals'])}"
            f" · {len(ch['regressions'])} regressions · {len(ch['fixes'])} fixes")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def render_markdown(run: Run, baseline: dict | None = None) -> str:
    s, st = run.summary, run.start
    git = st.get("git") or {}
    out = [f"# Eval run {run.run_id}", ""]
    if not run.complete:
        out += [f"> **Incomplete run:** the log has no `run_end` (crashed or interrupted). "
                f"Totals are from the {len(run.cases)} finished cases.", ""]
    rate = "-" if s["pass_rate"] is None else f"{s['pass_rate']:.2f}"
    out += [
        f"**{pass_line(s['totals'])}** · pass rate {rate}"
        + (f" · {s['incomplete']} incomplete" if s.get("incomplete") else ""),
        "",
        f"- date: {st.get('started_at', '?')} · {run.summary.get('seconds', '?')} s",
        f"- model: {models(run)}",
        f"- git: {git.get('sha')}{' (dirty)' if git.get('dirty') else ''} on {git.get('branch')}",
        f"- ask: `{st.get('ask')}` · judge: {'on (' + str(st.get('judge_model')) + ')' if st.get('judge') else 'off'}"
        f" · today: {st.get('today')}",
        "- mean scores: " + ", ".join(f"{k} {fmt_score(v)}" for k, v in s["mean_scores"].items()),
    ]
    if line := baseline_line(run, baseline):
        out.append(f"- {line}")
    if warn := version_warnings(run, baseline):
        out.append(f"- **metric versions differ from the baseline:** {', '.join(warn)}")
    out += ["", table(run.cases, baseline), ""]

    if baseline:
        ch = changes(run.cases, baseline)
        out += ["## Changes against the baseline", ""]
        if not any(ch.values()):
            out.append("No changes.")
        for cid, a, b in ch["regressions"]:
            out.append(f"- **regression** {cid}: {a} → {b}")
        for cid, a, b in ch["fixes"]:
            out.append(f"- fix {cid}: {a} → {b}")
        for cid, a, b in ch["score_changes"]:
            out.append(f"- score {cid}: {a:.2f} → {b:.2f} ({b - a:+.2f})")
        out.append("")

    failed = [c for c in run.cases if c["status"] in (Status.FAIL, Status.ERROR)]
    if failed:
        out += ["## Failures", ""]
        for c in failed:
            out += [f"### {case_label(c)}", "", "```text", failure_block(c), "```", ""]

    out += ["## Category counts", ""]
    counts = s.get("category_counts") or {}
    out += [f"- {cat}: {n}" for cat, n in counts.items()] or ["None."]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _pretty(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _needle_pattern(needle: str) -> re.Pattern:
    """Like metrics.contains(), on the raw text: case-insensitive, optional thousands commas,
    either minus sign."""
    needle = needle.replace(",", "") if re.fullmatch(r"[\d,.\-−]+", needle) else needle
    parts = []
    for i, ch in enumerate(needle):
        parts.append("[-−]" if ch in "-−" else re.escape(ch))
        if ch.isdigit() and needle[i + 1:i + 2].isdigit():
            parts.append(",?")
    left = r"(?<![\w.])" if needle[:1].isalnum() else ""
    right = r"(?!\w|\.\d)" if needle[-1:].isalnum() else ""
    return re.compile(left + "".join(parts) + right, re.IGNORECASE)


def highlight(text: str, items: list) -> str:
    """Escaped text with each found must_include alternative in <mark>."""
    spans = []
    for item in items:
        for alt in [item] if isinstance(item, str) else item:
            spans += [m.span() for m in _needle_pattern(alt).finditer(text)]
    out, pos = [], 0
    for a, b in sorted(spans):
        if a < pos:
            continue
        out += [esc(text[pos:a]), f'<mark>{esc(text[a:b])}</mark>']
        pos = b
    out.append(esc(text[pos:]))
    return "".join(out)


def rows_table(rows: list[dict], limit: int | None = None) -> str:
    if not rows:
        return '<p class="muted">no rows</p>'
    shown = rows[:limit] if limit else rows
    cols = list(dict.fromkeys(k for r in shown if isinstance(r, dict) for k in r))
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{esc(_cell(r.get(c)))}</td>" for c in cols) + "</tr>"
                   for r in shown if isinstance(r, dict))
    more = f'<p class="muted">{len(shown)} of {len(rows)} rows</p>' if len(shown) < len(rows) else ""
    return f'<div class="scroll"><table class="rows"><tr>{head}</tr>{body}</table></div>{more}'


def _cell(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)


def badge(status: str) -> str:
    return f'<span class="badge {esc(status)}">{esc(status)}</span>'


def chips(cats: list[str]) -> str:
    return "".join(f'<span class="chip">{esc(c)}</span>' for c in cats or [])


def _anchor(case_id: str) -> str:
    return "case-" + re.sub(r"[^\w-]", "_", case_id)


def _tool_card(call: dict, tool_step: dict | None, log_entry: dict | None) -> str:
    rows = (log_entry or {}).get("rows_preview")
    total = (log_entry or {}).get("row_count")
    status = (tool_step or {}).get("status", "ok")
    content = (tool_step or {}).get("content")
    parsed = None
    if content:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
    result = []
    if isinstance(parsed, dict):
        if parsed.get("error"):
            result.append(f'<p class="bad">error: {esc(parsed["error"])}</p>')
        if parsed.get("notes"):
            result.append("<p><b>notes:</b></p><ul>" + "".join(f"<li>{esc(n)}</li>" for n in parsed["notes"])
                          + "</ul>")
        if parsed.get("ids"):
            result.append(f'<p><b>ids:</b> <code>{esc(", ".join(map(str, parsed["ids"])))}</code></p>')
    if rows is not None:
        result.append(rows_table(rows) + f'<p class="muted">{len(rows)} of {total} rows</p>')
    elif isinstance(parsed, dict) and isinstance(parsed.get("rows"), list):
        result.append(rows_table(parsed["rows"])
                      + f'<p class="muted">{len(parsed["rows"])} of {parsed.get("row_count")} rows</p>')
    elif content:
        result.append(f'<pre class="json">{esc(content)}</pre>')
    summary_bits = [f"result {esc(log_entry['result_id'])}" if log_entry and log_entry.get("result_id")
                    else "result"]
    if total is not None:
        summary_bits.append(f"{total} row{'' if total == 1 else 's'}")
    if status != "ok":
        summary_bits.append(f'<span class="bad">{esc(status)}</span>')
    return (f'<div class="card tool"><div class="tool-name">🔧 {esc(call.get("name"))}</div>'
            f'<pre class="json">{esc(_pretty(call.get("args")))}</pre>'
            f'<details><summary>{" · ".join(summary_bits)}</summary>{"".join(result)}</details></div>')


def _step_meta(step: dict) -> str:
    bits = []
    if step.get("model"):
        bits.append(esc(step["model"]))
    if u := step.get("usage"):
        bits.append(f"{u.get('input_tokens')} in / {u.get('output_tokens')} out tokens")
    if step.get("finish_reason"):
        bits.append(esc(step["finish_reason"]))
    return f'<div class="meta">{" · ".join(bits)}</div>' if bits else ""


def _turn_html(case: dict, i: int, answer: dict, user: str, scored: bool, users: dict) -> str:
    trace = answer.get("trace") or []
    log = [c for c in case.get("tool_calls") or [] if c.get("turn") == i]
    by_id = {c["id"]: c for c in log if c.get("id")}
    tool_steps = {s["tool_call_id"]: s for s in trace if s.get("kind") == "tool"}
    final_text = answer.get("answer") or ""
    out = [f'<div class="turn"><h4>Turn {i + 1}</h4>']
    user_name = users.get(user, user)
    user_steps = [s for s in trace if s.get("kind") == "user"]
    message = user_steps[0]["text"] if user_steps else None
    if message is None:
        message = case.get("question") if "question" in case else case["turns"][i]["message"]
    out.append(f'<div class="step user"><div class="who">{esc(user_name)} <span class="muted">'
               f'{esc(user)}</span></div><div class="text">{esc(message)}</div></div>')
    unmatched_log = list(log)
    for step in trace:
        if step.get("kind") == "ai":
            parts = [f'<div class="step ai"><div class="who">copilot</div>{_step_meta(step)}']
            if step.get("reasoning"):
                parts.append(f'<details class="reasoning" open><summary>reasoning</summary>'
                             f'<div class="text">{esc(step["reasoning"])}</div></details>')
            text = step.get("text") or ""
            if text.strip() and text != final_text:
                parts.append(f'<div class="text">{esc(text)}</div>')
            elif text.strip():
                parts.append('<div class="muted">final answer (below)</div>')
            for call in step.get("tool_calls") or []:
                entry = by_id.get(call.get("id"))
                if entry in unmatched_log:
                    unmatched_log.remove(entry)
                parts.append(_tool_card(call, tool_steps.get(call.get("id")), entry))
            parts.append("</div>")
            out.append("".join(parts))
    for entry in unmatched_log:            # no trace (old log or error): cards from the log
        out.append(_tool_card({"name": entry["name"], "args": entry["args"]}, None, entry))
    for block in answer.get("blocks") or []:
        out.append(
            f'<div class="card visual"><div class="tool-name">📊 {esc(block.get("type"))}: '
            f'{esc(block.get("title"))}</div><p class="muted">source {esc(block.get("source"))}</p>'
            f'<pre class="json">{esc(_pretty(block.get("fields")))}</pre>'
            f'<details><summary>{len(block.get("rows") or [])} rows</summary>'
            f'{rows_table(block.get("rows") or [], limit=100)}</details></div>')
    if answer.get("error"):
        out.append(f'<pre class="error">{esc(answer["error"])}</pre>')
    items = (case.get("expected") or {}).get("must_include", []) if scored else []
    if final_text:
        out.append(f'<div class="final"><div class="who">answer</div>'
                   f'<div class="text">{highlight(final_text, items)}</div></div>')
    out.append("</div>")
    return "".join(out)


def _metrics_html(case: dict) -> str:
    rows = []
    for m in case["metrics"]:
        score = "" if m.get("score") is None else f"{m['score']:.2f}"
        version = f" v{m['version']}" if m.get("version") else ""
        rows.append(f'<tr><td>{esc(m["name"])}{version}</td><td>{badge(m["status"])}</td>'
                    f'<td>{score}</td><td>{esc(m.get("reason") or m.get("error"))}</td></tr>')
    out = ['<div class="scroll"><table class="metrics"><tr><th>metric</th><th>status</th>'
           '<th>score</th><th>reason</th></tr>', *rows, "</table></div>"]
    fact = metric(case, "FactRecall")
    if fact and fact.get("details"):
        d = fact["details"]
        items = [f'<li class="good">✓ {esc(i)}</li>' for i in d.get("found", [])]
        for i in d.get("missing", []):
            where = "generation" if i["in_tool_results"] else "retrieval"
            tools = f" (in {esc(', '.join(i['tools']))})" if i["tools"] else ""
            alts = f' <span class="muted">or {esc(" | ".join(i["alternatives"][1:]))}</span>' \
                if len(i["alternatives"]) > 1 else ""
            items.append(f'<li class="bad">✗ {esc(i["item"])}{alts} <span class="tag">{where}</span>{tools}</li>')
        items += [f'<li class="bad">✗ forbidden: {esc(i)} <span class="tag">forbidden</span></li>'
                  for i in d.get("forbidden", [])]
        out.append(f'<p><b>FactRecall items</b></p><ul class="items">{"".join(items)}</ul>')
    vis = metric(case, "VisualMatch")
    if vis and vis.get("details"):
        out.append(f'<p><b>VisualMatch:</b> expected {esc(vis["details"].get("expected") or "none")}, '
                   f'got {esc(", ".join(vis["details"].get("actual") or []) or "no blocks")}</p>')
    judge = metric(case, "Judge")
    if judge and judge.get("details"):
        out.append(f'<p><b>Judge rubric</b> ({esc(judge["details"].get("evaluation_model"))}): '
                   f'{esc(judge["details"].get("rubric"))}</p>')
    elif (rubric := (case.get("expected") or {}).get("rubric")):
        out.append(f'<p class="muted"><b>rubric</b> (not judged): {esc(rubric)}</p>')
    return "".join(out)


def _case_html(case: dict, users: dict) -> str:
    cid = case["case_id"]
    head = [f'<a href="#{_anchor(cid)}">{esc(case_label(case))}</a>', badge(case["status"]),
            f'<span class="score">score {fmt_score(case.get("score"))}</span>',
            f'<span class="muted">{case.get("seconds") or 0:.1f} s · {esc(case.get("model"))}</span>',
            chips(case.get("categories"))]
    if case.get("incomplete"):
        head.append('<span class="chip">incomplete</span>')
    out = [f'<section class="case" id="{_anchor(cid)}" data-status="{esc(case["status"])}">',
           f'<h2>{" ".join(head)}</h2>', _metrics_html(case)]
    if case.get("error"):
        out.append(f'<details open><summary class="bad">error</summary><pre class="error">'
                   f'{esc(case["error"])}</pre></details>')
    answers = case.get("answers") or []
    turn_users = [case.get("user_id", "")] if "question" in case else [t["user_id"] for t in case["turns"]]
    out.append("<h3>Timeline</h3>")
    for i, answer in enumerate(answers):
        out.append(_turn_html(case, i, answer, turn_users[i] if i < len(turn_users) else "?",
                              scored=i == len(answers) - 1, users=users))
    if not answers:
        out.append('<p class="muted">no answers</p>')
    out.append('<p><a href="#top">↑ top</a></p></section>')
    return "".join(out)


CSS = """
*{box-sizing:border-box}
body{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
 color:#1f2328;background:#f6f8fa}
.wrap{max-width:1100px;margin:0 auto;padding:12px}
header,.case{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:12px 16px;margin:12px 0}
h1{font-size:20px;margin:4px 0}h2{font-size:17px;margin:4px 0 8px}h3{font-size:15px;margin:14px 0 6px}
h4{font-size:13px;margin:10px 0 4px;color:#57606a;text-transform:uppercase;letter-spacing:.04em}
a{color:#0969da;text-decoration:none}a:hover{text-decoration:underline}
pre,code,.json{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
pre{white-space:pre-wrap;word-break:break-word;background:#f6f8fa;border:1px solid #eaeef2;border-radius:6px;
 padding:6px 8px;margin:4px 0;max-height:400px;overflow:auto}
pre.error{background:#fff1f0;border-color:#ffccc7;color:#a8071a}
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;font-size:13px;margin:6px 0}
th,td{border:1px solid #d0d7de;padding:3px 7px;text-align:left;vertical-align:top}
th{background:#f6f8fa}
table.rows td{font-family:ui-monospace,Menlo,monospace;font-size:12px;white-space:nowrap}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}
.badge.PASS{background:#1a7f37}.badge.FAIL{background:#cf222e}.badge.ERROR{background:#9a6700}
.badge.SKIP{background:#8c959f}
.chip,.tag{display:inline-block;padding:0 6px;border-radius:4px;background:#eaeef2;font-size:12px;
 font-weight:normal;margin-left:3px}
.tag{background:#ffebe9;color:#a40e26}
.muted{color:#57606a;font-weight:normal;font-size:12px}
.good{color:#1a7f37}.bad{color:#cf222e}
ul.items{margin:4px 0;padding-left:20px}
.score{font-weight:normal;font-size:14px}
.turn{border-left:3px solid #d0d7de;padding-left:10px;margin:8px 0}
.step,.final{border-radius:6px;padding:6px 10px;margin:6px 0}
.step.user{background:#ddf4ff}.step.ai{background:#fbfbfc;border:1px solid #eaeef2}
.final{background:#f0fff4;border:1px solid #aceebb}
.who{font-weight:600;font-size:12px}.meta{color:#57606a;font-size:11px}
.text{white-space:pre-wrap;word-break:break-word}
.card{border:1px solid #d0d7de;border-radius:6px;padding:6px 8px;margin:6px 0;background:#fff}
.tool-name{font-weight:600;font-family:ui-monospace,Menlo,monospace}
.reasoning .text{color:#57606a;font-style:italic}
mark{background:#aceebb;padding:0 2px;border-radius:3px}
summary{cursor:pointer}
.filters button{border:1px solid #d0d7de;background:#fff;border-radius:6px;padding:3px 10px;margin-right:4px;
 cursor:pointer}
.filters button.on{background:#0969da;color:#fff;border-color:#0969da}
.warn{background:#fff8c5;border:1px solid #d4a72c;border-radius:6px;padding:6px 10px}
@media (max-width:600px){.wrap{padding:4px}header,.case{padding:8px}}
"""

JS = """
document.querySelectorAll('[data-filter]').forEach(function(b){b.addEventListener('click',function(){
 var f=b.getAttribute('data-filter');
 document.querySelectorAll('[data-status]').forEach(function(el){
  el.hidden=(f!=='all'&&el.getAttribute('data-status')!==f);});
 document.querySelectorAll('[data-filter]').forEach(function(x){x.classList.toggle('on',x===b);});});});
"""


def render_html(run: Run, baseline: dict | None = None) -> str:
    s, st = run.summary, run.start
    git = st.get("git") or {}
    users = st.get("users") or {}
    rate = "-" if s["pass_rate"] is None else f"{s['pass_rate']:.2f}"
    meta = [
        ("date", st.get("started_at")), ("seconds", s.get("seconds")), ("model", models(run)),
        ("git", f"{git.get('sha')}{' (dirty)' if git.get('dirty') else ''} on {git.get('branch')}"),
        ("ask", st.get("ask")),
        ("judge", f"on ({st.get('judge_model')})" if st.get("judge") else "off"),
        ("today", st.get("today")), ("db", (st.get("db") or {}).get("path")),
        ("mean scores", ", ".join(f"{k} {fmt_score(v)}" for k, v in s["mean_scores"].items())),
    ]
    head = [f'<header id="top"><h1>Eval run {esc(run.run_id)}</h1>']
    if not run.complete:
        head.append(f'<p class="warn"><b>Incomplete run:</b> the log has no run_end (crashed or '
                    f'interrupted). Totals are from the {len(run.cases)} finished cases.</p>')
    head.append(f'<p style="font-size:16px"><b>{esc(pass_line(s["totals"]))}</b> · pass rate {rate}'
                + (f" · {s['incomplete']} incomplete" if s.get("incomplete") else "") + "</p>")
    if line := baseline_line(run, baseline):
        head.append(f"<p>{esc(line)}</p>")
    if warn := version_warnings(run, baseline):
        head.append(f'<p class="warn">Metric versions differ from the baseline: {esc(", ".join(warn))}</p>')
    head.append('<div class="scroll"><table>' + "".join(
        f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in meta) + "</table></div>")
    if baseline:
        ch = changes(run.cases, baseline)
        items = [f'<li class="bad">regression <a href="#{_anchor(c)}">{esc(c)}</a>: {esc(a)} → {esc(b)}</li>'
                 for c, a, b in ch["regressions"]]
        items += [f'<li class="good">fix <a href="#{_anchor(c)}">{esc(c)}</a>: {esc(a)} → {esc(b)}</li>'
                  for c, a, b in ch["fixes"]]
        items += [f'<li>score <a href="#{_anchor(c)}">{esc(c)}</a>: {a:.2f} → {b:.2f} ({b - a:+.2f})</li>'
                  for c, a, b in ch["score_changes"]]
        head.append("<h3>Changes against the baseline</h3>"
                    + (f"<ul>{''.join(items)}</ul>" if items else "<p>No changes.</p>"))
    counts = s.get("category_counts") or {}
    head.append("<h3>Category counts</h3>" + (
        "<ul>" + "".join(f"<li>{esc(k)}: {n}</li>" for k, n in counts.items()) + "</ul>"
        if counts else "<p>None.</p>"))
    head.append("</header>")

    rows = table_rows(run.cases, baseline)
    body = []
    for c, row in zip(run.cases, rows):
        cells = [f'<a href="#{_anchor(c["case_id"])}">{esc(row[0])}</a>', badge(c["status"]),
                 *map(esc, row[2:])]
        body.append(f'<tr data-status="{esc(c["status"])}">' + "".join(f"<td>{x}</td>" for x in cells) + "</tr>")
    summary = ['<section class="case"><div class="filters">'
               '<button data-filter="all" class="on">All</button>'
               '<button data-filter="FAIL">Failures</button>'
               '<button data-filter="ERROR">Errors</button></div>'
               '<div class="scroll"><table><tr>' + "".join(f"<th>{esc(h)}</th>" for h in TABLE_HEADER)
               + "</tr>" + "".join(body) + "</table></div></section>"]
    cases = [_case_html(c, users) for c in run.cases]
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>Eval {esc(run.run_id)}</title><style>{CSS}</style></head>"
            f'<body><div class="wrap">{"".join(head)}{"".join(summary)}{"".join(cases)}</div>'
            f"<script>{JS}</script></body></html>")


# ---------------------------------------------------------------------------
# Files: reports, history, baseline
# ---------------------------------------------------------------------------

def write_html(run: Run, baseline: dict | None = None, out_dir: Path = REPORTS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run.run_id}.html"
    path.write_text(render_html(run, baseline))
    return path


def write_reports(run: Run, baseline: dict | None = None, out_dir: Path = REPORTS_DIR) -> tuple[Path, Path, str]:
    """evals/reports/<run_id>.md and .html. Returns (md path, html path, markdown)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(run, baseline)
    md_path = out_dir / f"{run.run_id}.md"
    md_path.write_text(md)
    return md_path, write_html(run, baseline, out_dir), md


def _model_column(start: dict) -> str | None:
    """MODEL, or the ask() under test when it is not the real one (e.g. evals.fake:ask)."""
    ask = start.get("ask") or "copilot.api:ask"
    return start.get("model") if ask == "copilot.api:ask" else ask


def history_row(run: Run) -> dict:
    s, st = run.summary, run.start
    git = st.get("git") or {}
    means = s["mean_scores"]
    return {"run_id": run.run_id, "date": (st.get("started_at") or "")[:10], "sha": git.get("sha"),
            "dirty": git.get("dirty"), "model": _model_column(st), "cases": s["cases"],
            "pass": s["totals"][Status.PASS], "fail": s["totals"][Status.FAIL],
            "error": s["totals"][Status.ERROR], "pass_rate": s["pass_rate"],
            "mean_fact_recall": means.get("FactRecall"), "mean_visual": means.get("VisualMatch"),
            "mean_judge": means.get("Judge"), "seconds": s.get("seconds")}


def append_history(run: Run, path: Path = HISTORY) -> dict:
    row = history_row(run)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({k: "" if v is None else v for k, v in row.items()})
    return row


def baseline_from(run: Run) -> dict:
    return {"run_id": run.run_id, "sha": (run.start.get("git") or {}).get("sha"),
            "model": run.start.get("model"), "metric_versions": run.start.get("metric_versions"),
            "cases": {c["case_id"]: {"status": c["status"], "score": c.get("score")}
                      for c in run.cases if not c.get("as_dependency")}}


def write_baseline(run: Run, path: Path = BASELINE) -> dict:
    data = baseline_from(run)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.report", description=__doc__.split("\n\n")[0])
    p.add_argument("run", nargs="?", help="run log path or run id (default: newest in evals/runs/)")
    p.add_argument("--baseline", type=Path, default=BASELINE, help=f"default: {BASELINE}")
    p.add_argument("--record", action="store_true", help=f"append a row to {HISTORY}")
    p.add_argument("--set-baseline", action="store_true", help=f"write {BASELINE} from this run")
    p.add_argument("--out-dir", type=Path, default=REPORTS_DIR, help=argparse.SUPPRESS)
    p.add_argument("--history", type=Path, default=HISTORY, help=argparse.SUPPRESS)
    a = p.parse_args(argv)

    run = load_run(find_run(a.run))
    baseline = load_baseline(a.baseline)
    md_path, html_path, md = write_reports(run, baseline, a.out_dir)
    print(md)
    print(f"report: {md_path}\nhtml:   {html_path}")
    if (a.record or a.set_baseline) and not run.complete:
        print("incomplete run (no run_end): not recorded", file=sys.stderr)
        return 1
    if a.record:
        append_history(run, a.history)
        print(f"history: appended {run.run_id} to {a.history}")
    if a.set_baseline:
        regressions = changes(run.cases, baseline)["regressions"]
        if regressions:
            print(f"note: {len(regressions)} regressions against the old baseline; say why in the "
                  "commit message", file=sys.stderr)
        write_baseline(run, a.baseline)
        print(f"baseline: {a.baseline} = {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
