"""Feedback from users: corrections, shared notes and user rules. Owner: D.

Each tool writes one row to `corrections`, `notes` or `rules` (db/schema.sql). The views apply
them, so every read tool and every user sees them at once; the original values stay in the
source tables. The author is the user in the run config, never a tool argument. Timestamps use
the copilot's today (the `settings` table), so they line up with the dates the tools compare.
"""

from contextlib import closing
from datetime import UTC, date, datetime

from langchain_core.runnables import RunnableConfig

from copilot import db, results
from copilot.memory import user_profile
from copilot.tools.base import ToolResult, fmt_value, run_context, user_rule_cite

# inspections field -> correction kind. Temperatures are readings (raw data); spill fields come
# from the AI's image analysis.
CORRECTABLE = {
    "wellhead_temp_c": "raw_data",
    "ambient_temp_c": "raw_data",
    "spill_detected": "ai_analysis",
    "spill_est_volume_bbl": "ai_analysis",
    "spill_area_pct": "ai_analysis",
}
FIELD_ALIASES = {"spill_volume_bbl": "spill_est_volume_bbl", "air_temp_c": "ambient_temp_c"}
EFFECTIVE = {"spill_est_volume_bbl": "spill_volume_bbl"}   # field -> column in inspections_effective


def _result(kind: str, rows: list[dict], ids: list[str], notes: list[str]) -> ToolResult:
    return ToolResult(result_id=results.put(kind, rows), kind=kind, rows=rows,
                      ids=list(dict.fromkeys(i for i in ids if i)), notes=notes)


def _author(config: RunnableConfig | None) -> tuple[dict | None, str | None]:
    """(profile, thread_id) of the user who is talking; profile None if unknown."""
    c = run_context(config)
    return user_profile(c.get("user_id")), c.get("thread_id")


def _not_identified(kind: str) -> ToolResult:
    return _result(kind, [], [], ["the user is not identified, so nothing was recorded; ask who they are"])


def _stamp() -> str:
    """Now, on the copilot's calendar: today's date with the current UTC time."""
    return f"{db.today()}T{datetime.now(UTC):%H:%M:%S}Z"


def _next_id(prefix: str, asset_id: str, table: str, column: str) -> str:
    """'<prefix>-0164-001', numbered per well."""
    stem = f"{prefix}-{asset_id.removeprefix('WELL-')}-"
    n = db.rows(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} LIKE ?", (stem + "%",))[0]["n"]
    return f"{stem}{n + 1:03d}"


def _bad_date(*values: str | None) -> str | None:
    for v in values:
        if v is None:
            continue
        try:
            date.fromisoformat(v)
        except (TypeError, ValueError):
            return f"invalid date '{v}'; use YYYY-MM-DD"
    return None


def _cite(rule_id: int | None) -> str | None:
    """Citation for a rules row: '<doc_id> § <section>' or 'user rule N by <name>'."""
    if rule_id is None:
        return None
    r = db.rows("SELECT rule_id, doc_id, section_path, author_user_id FROM rules WHERE rule_id = ?", (rule_id,))
    if not r:
        return None
    r = r[0]
    if r["doc_id"]:
        return f"{r['doc_id']} § {r['section_path']}" if r["section_path"] else r["doc_id"]
    return user_rule_cite(r["rule_id"], r["author_user_id"])


# ---------------------------------------------------------------------------
# record_correction
# ---------------------------------------------------------------------------


def _inspection(inspection_id: str) -> dict | None:
    """One inspection with corrections applied, its producing verdict and its spill class."""
    found = db.rows(
        """
        SELECT e.inspection_id, e.asset_id, e.well_type, e.inspected_at, e.inspected_date,
               u.name AS inspector_name, e.notes AS inspection_notes,
               e.raw_wellhead_temp_c, e.raw_ambient_temp_c, e.raw_spill_detected,
               e.raw_spill_est_volume_bbl, e.raw_spill_area_pct,
               e.wellhead_temp_c, e.ambient_temp_c, e.temp_delta_c, e.producing_threshold_c,
               e.producing_rule_id, e.is_producing, e.spill_detected, e.spill_volume_bbl, e.spill_area_pct,
               s.spill_class, s.is_reportable, s.maintenance_id, s.report_path
        FROM inspections_effective e
        LEFT JOIN users u ON u.user_id = e.inspector_user_id
        LEFT JOIN spills s ON s.inspection_id = e.inspection_id
        WHERE e.inspection_id = ?
        """,
        (inspection_id,),
    )
    if not found:
        return None
    r = found[0]
    for k in ("is_producing", "spill_detected", "is_reportable"):
        r[k] = None if r[k] is None else bool(r[k])
    if r["temp_delta_c"] is not None:
        r["temp_delta_c"] = round(r["temp_delta_c"], 1)
    return r


def _find_inspection(inspection_id: str | None, asset_id: str | None, on: str | None) -> tuple[str | None, str | None]:
    """(inspection_id, None) or (None, note). By ID, or by well and inspection date."""
    if inspection_id:
        if db.rows("SELECT 1 FROM inspections WHERE inspection_id = ?", (inspection_id,)):
            return inspection_id, None
        return None, f"unknown inspection '{inspection_id}'"
    if not (asset_id and on):
        return None, "give inspection_id, or asset_id and date"
    if note := _bad_date(on):
        return None, note
    found = db.rows("SELECT inspection_id FROM inspections WHERE asset_id = ? AND substr(inspected_at, 1, 10) = ?",
                    (asset_id, on))
    if found:
        return found[0]["inspection_id"], None
    near = db.rows(
        """SELECT inspection_id, substr(inspected_at, 1, 10) AS d FROM inspections WHERE asset_id = ?
           ORDER BY abs(julianday(substr(inspected_at, 1, 10)) - julianday(?)) LIMIT 3""",
        (asset_id, on))
    if not near:
        return None, f"no inspections of '{asset_id}'"
    return None, (f"no inspection of {asset_id} on {on}; nearest: "
                  + ", ".join(f"{n['inspection_id']} ({n['d']})" for n in near))


def record_correction(
    field: str,
    corrected_value: float,
    reason: str,
    inspection_id: str | None = None,
    asset_id: str | None = None,
    date: str | None = None,
    *,
    config: RunnableConfig,
) -> ToolResult:
    """Record a user's correction of one inspection value. Every later answer, for every user, uses it.

    Use it when the user says a recorded value is wrong: a reading ("the wellhead was really
    41.0 °C"), or the AI's spill analysis ("the spill was 5.4 bbl, not 4.5", "that was not a spill").
    `field`: wellhead_temp_c | ambient_temp_c | spill_est_volume_bbl | spill_detected (1 = spill,
    0 = no spill) | spill_area_pct. Give `inspection_id`, or `asset_id` and the inspection `date`.
    `reason`: why, in the user's words. The original value is kept; the user is the author.

    Returns the inspection before and after: °C above air vs. the threshold and producing yes/no,
    or the spill class, reportable yes/no and the spill rule checks (SR-01, SR-02, SR-03). Notes
    flag what may disagree with the correction (e.g. the inspector's note); tell the user.
    """
    kind = "record_correction"
    profile, thread_id = _author(config)
    if profile is None:
        return _not_identified(kind)
    field = FIELD_ALIASES.get(field, field)
    if field not in CORRECTABLE:
        return _result(kind, [], [], [f"unknown field '{field}'; valid: {', '.join(CORRECTABLE)}"])
    iid, note = _find_inspection(inspection_id, asset_id, date)
    if note:
        return _result(kind, [], [], [note])

    before = _inspection(iid)
    column = EFFECTIVE.get(field, field)
    original, previous = before[f"raw_{field}"], before[column]
    if previous is not None and float(previous) == float(corrected_value):
        return _result(kind, [before], [iid], [f"{iid} {field} is already {fmt_value(corrected_value, field)}; nothing recorded"])

    a = before["asset_id"]
    cid = _next_id("COR", a, "corrections", "correction_id")
    with closing(db.connect(read_only=False)) as conn, conn:
        superseded = conn.execute(
            "UPDATE corrections SET status = 'superseded' WHERE source = 'copilot' AND status = 'active' "
            "AND target_table = 'inspections' AND target_id = ? AND field = ?", (iid, field)).rowcount
        conn.execute(
            """INSERT INTO corrections (correction_id, source, kind, target_table, target_id, asset_id, field,
                   original_value, corrected_value, author_user_id, reason, created_at, conversation_id)
               VALUES (?, 'copilot', ?, 'inspections', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, CORRECTABLE[field], iid, a, field, original, corrected_value, profile["user_id"], reason,
             _stamp(), thread_id))
    after = _inspection(iid)
    if field != "spill_detected":
        corrected_value = float(corrected_value)
        for r in (before, after):
            for k in ("wellhead_temp_c", "ambient_temp_c", "spill_volume_bbl", "spill_area_pct"):
                r[k] = None if r[k] is None else float(r[k])

    name = profile["name"]
    row = {
        "section": "correction", "correction_id": cid, "inspection_id": iid, "asset_id": a,
        "well_type": after["well_type"], "inspected_at": after["inspected_at"],
        "inspector_name": after["inspector_name"], "inspection_notes": after["inspection_notes"] or None,
        "field": field, "kind": CORRECTABLE[field], "original_value": original,
        "previous_value": previous, "corrected_value": corrected_value, "corrected_by": name, "reason": reason,
        "wellhead_temp_c": after["wellhead_temp_c"], "ambient_temp_c": after["ambient_temp_c"],
        "temp_delta_c_before": before["temp_delta_c"], "temp_delta_c": after["temp_delta_c"],
        "producing_threshold_c": after["producing_threshold_c"],
        "is_producing_before": before["is_producing"], "is_producing": after["is_producing"],
    }
    rows, ids = [row], [cid, iid]
    flipped = False   # the correction changes whether the well is producing, or whether there was a spill
    notes = [f"recorded {cid}: {iid} {field} {fmt_value(original, field)} -> {fmt_value(corrected_value, field)} by {name}; "
             f"the original value {fmt_value(original, field)} is kept"]
    if superseded:
        notes.append(f"replaces an earlier correction of {iid} {field}")

    if field in ("wellhead_temp_c", "ambient_temp_c"):
        ids.append(_cite(after["producing_rule_id"]))
    if field in ("wellhead_temp_c", "ambient_temp_c") and before["is_producing"] != after["is_producing"]:
        flipped = True
        verdict = "producing oil" if after["is_producing"] else "not producing oil"
        notes.append(f"{a} is now {verdict} at {iid}: wellhead {fmt_value(after['wellhead_temp_c'])} °C against "
                     f"{fmt_value(after['ambient_temp_c'])} °C air, {fmt_value(after['temp_delta_c'])} °C above air "
                     f"(threshold {fmt_value(after['producing_threshold_c'])} °C, {_cite(after['producing_rule_id'])})")

    if field.startswith("spill"):
        from copilot.tools.records import _findings, _well_rules  # records imports base, not this module

        row |= {"spill_volume_bbl_before": before["spill_volume_bbl"], "spill_volume_bbl": after["spill_volume_bbl"],
                "spill_class_before": before["spill_class"], "spill_class": after["spill_class"],
                "is_reportable_before": before["is_reportable"], "is_reportable": after["is_reportable"],
                "maintenance_id": after["maintenance_id"] or before["maintenance_id"],
                "report_path": after["report_path"] or before["report_path"]}
        ids.append(row["maintenance_id"])
        if before["spill_class"] != after["spill_class"]:
            notes.append(f"spill class {before['spill_class'] or 'no spill'} -> {after['spill_class'] or 'no spill'}; "
                         f"reportable {before['is_reportable']} -> {after['is_reportable']}")
            if row["maintenance_id"]:
                notes.append(f"repair {row['maintenance_id']} and its report were written for the old value "
                             f"(class {before['spill_class'] or 'no spill'}); that class no longer holds")
        if after["spill_detected"]:
            found_on = after["inspected_date"]
            checks = _findings(a, found_on, found_on, db.today(), _well_rules(a), notes)
            for f in checks:
                if iid in f["ids"] and f["rule"] in ("SR-01", "SR-02", "SR-03"):
                    rows.append({"section": "finding", **f})
                    ids += [*f["ids"], f.get("cite")]
                    if f["status"] in ("breach", "open"):
                        notes.append(f"{f['rule']} {f['status']}: {f['detail']}")

    flipped = flipped or (field == "spill_detected" and bool(before["spill_detected"]) != bool(after["spill_detected"]))
    if flipped and row["inspection_notes"]:
        notes.append(f"the inspection note '{row['inspection_notes']}' ({row['inspector_name']}) may disagree "
                     f"with the correction; if it does, say so and ask {name} to confirm")
    return _result(kind, rows, ids, notes)


# ---------------------------------------------------------------------------
# add_note
# ---------------------------------------------------------------------------


def _latest_inspection(asset_id: str) -> dict | None:
    found = db.rows(
        """SELECT s.inspection_id, substr(s.inspected_at, 1, 10) AS inspected_date, u.name AS inspector_name,
                  s.ambient_temp_c, s.wellhead_temp_c, s.temp_delta_c, s.producing_threshold_c, s.is_producing,
                  s.inspection_notes, s.correction_ids
           FROM well_status_now s LEFT JOIN users u ON u.user_id = s.inspector_user_id
           WHERE s.asset_id = ?""", (asset_id,))
    if not found:
        return None
    r = found[0]
    r["is_producing"] = None if r["is_producing"] is None else bool(r["is_producing"])
    r["temp_delta_c"] = None if r["temp_delta_c"] is None else round(r["temp_delta_c"], 1)
    return r


def _other_notes(asset_id: str, note_id: str, today: str) -> list[dict]:
    """Notes on the well that are valid now or later (not corrections), oldest first."""
    return db.rows(
        """SELECT n.note_id, n.source, u.name AS author_name, substr(n.created_at, 1, 10) AS date, n.text,
                  n.valid_from, n.valid_to, n.claim_status
           FROM notes n LEFT JOIN users u ON u.user_id = n.author_user_id
           WHERE n.asset_id = :a AND n.note_id <> :id AND n.note_type <> 'correction'
             AND COALESCE(n.claim_status, '') <> 'retracted' AND :today <= COALESCE(n.valid_to, :today)
           ORDER BY n.created_at, n.note_id""", {"a": asset_id, "id": note_id, "today": today})


def add_note(
    asset_id: str,
    text: str,
    valid_from: str | None = None,
    valid_to: str | None = None,
    claims_producing: bool | None = None,
    *,
    config: RunnableConfig,
) -> ToolResult:
    """Save what a user tells you about a well, as a note that every user sees from now on.

    Use it for facts and plans: "WELL-0007 will be shut in from 17 Oct for 10 days", "WELL-0175 is
    running fine", "waiting on parts". `text`: the fact in the user's words. `valid_from` /
    `valid_to`: the dates it covers (YYYY-MM-DD; valid_from defaults to today, valid_to open-ended).
    `claims_producing`: true if the note says the well is producing oil now ("running fine",
    "back online"), false if it says it is not ("shut in", "down"), null if neither or only planned.

    A claim is checked against the latest inspection: kept as 'consistent', or as 'unconfirmed'
    when the data disagrees. The result has that inspection and the other notes on the well, so
    you can show the user what agrees and what does not and ask them to confirm.
    """
    kind = "add_note"
    profile, thread_id = _author(config)
    if profile is None:
        return _not_identified(kind)
    if not db.rows("SELECT 1 FROM wells WHERE asset_id = ?", (asset_id,)):
        return _result(kind, [], [], [f"unknown well '{asset_id}'"])
    today = db.today()
    valid_from = valid_from or today
    if note := _bad_date(valid_from, valid_to):
        return _result(kind, [], [], [note])

    latest = _latest_inspection(asset_id)
    status, notes = None, []
    if claims_producing is not None and latest and latest["is_producing"] is not None:
        if valid_from > today:
            notes.append(f"the note starts on {valid_from}, after today; it is not checked against the data")
        else:
            agrees = latest["is_producing"] == claims_producing
            status = "consistent" if agrees else "unconfirmed"
            verdict = "producing oil" if latest["is_producing"] else "not producing oil"
            evidence = (f"{latest['inspection_id']} ({latest['inspected_date']}, {latest['inspector_name']}): "
                        f"{fmt_value(latest['temp_delta_c'])} °C above air, threshold {fmt_value(latest['producing_threshold_c'])} °C, "
                        f"so {verdict}")
            notes.append(f"the claim matches {evidence}" if agrees else
                         f"the claim disagrees with {evidence}. Kept as unconfirmed: tell the user what the data "
                         f"shows and ask them to confirm")

    nid = _next_id("NOTE", asset_id, "notes", "note_id")
    with closing(db.connect(read_only=False)) as conn, conn:
        conn.execute(
            """INSERT INTO notes (note_id, source, asset_id, created_at, author_user_id, note_type, text,
                   valid_from, valid_to, claim_status, conversation_id)
               VALUES (?, 'copilot', ?, ?, ?, 'user_note', ?, ?, ?, ?, ?)""",
            (nid, asset_id, _stamp(), profile["user_id"], text, valid_from, valid_to, status, thread_id))

    others = _other_notes(asset_id, nid, today)
    notes.insert(0, f"recorded {nid} by {profile['name']}: '{text}' ({valid_from} to {valid_to or 'open'}); "
                    "every user sees it")
    if others:
        notes.append("other notes on this well: " + "; ".join(
            f"{o['note_id']} by {o['author_name'] or 'unknown'} ({o['date']}"
            + (f", {o['claim_status']}" if o["claim_status"] else "") + f"): '{o['text']}'" for o in others))
    row = {"note_id": nid, "asset_id": asset_id, "author_name": profile["name"], "text": text,
           "valid_from": valid_from, "valid_to": valid_to, "claim_status": status,
           "latest_inspection": latest, "other_notes": others}
    ids = [nid, latest["inspection_id"] if latest else None, *[o["note_id"] for o in others]]
    return _result(kind, [row], ids, notes)


# ---------------------------------------------------------------------------
# set_rule
# ---------------------------------------------------------------------------


def _rule_values(rule_key: str) -> list[dict]:
    """The effective value of a rule per well type: value, where it comes from, how many wells."""
    return db.rows(
        """SELECT w.well_type, r.value, r.unit, r.rule_id, r.source, r.scope, r.doc_id, r.section_path,
                  COUNT(*) AS wells
           FROM well_rules r JOIN wells w ON w.asset_id = r.asset_id
           WHERE r.rule_key = ?
           GROUP BY w.well_type, r.value, r.rule_id ORDER BY w.well_type, r.value""", (rule_key,))


def _describe(v: dict) -> str:
    return f"{v['well_type']}: {v['value']:g} {v['unit'] or ''} from {_cite(v['rule_id'])} ({v['wells']} wells)"


def set_rule(
    rule_key: str,
    value: float,
    reason: str,
    well_type: str | None = None,
    asset_id: str | None = None,
    *,
    config: RunnableConfig,
) -> ToolResult:
    """Set a threshold or limit that a user gives, for one well, one well type, or all wells.

    Use it when the user changes a rule: "for all T350 wells, a root-cause analysis after 2
    repairs, not 3". Apply it at exactly the scope the user gives: `asset_id` for one well,
    `well_type` for a type, neither for every well. A user rule wins over the manuals within its scope only.
    `rule_key`, e.g.: rca_corrective_count (corrective repairs on one equipment before a root-cause
    analysis), rca_window_months, production_min_delta_c (°C above air to count as producing),
    spill_reportable_min_bbl, containment_max_hours, spill_notice_hours, cleanup_verification_days,
    nov_response_days. `reason`: the user's words.

    Returns the rule before and after for the wells in scope, and the values the other wells keep.
    """
    kind = "set_rule"
    profile, thread_id = _author(config)
    if profile is None:
        return _not_identified(kind)
    keys = db.rows("SELECT DISTINCT rule_key, unit FROM rules WHERE source = 'document' ORDER BY rule_key")
    unit = next((k["unit"] for k in keys if k["rule_key"] == rule_key), None)
    if not any(k["rule_key"] == rule_key for k in keys):
        return _result(kind, [], [], [f"unknown rule_key '{rule_key}'; valid: "
                                      + ", ".join(f"{k['rule_key']} ({k['unit']})" for k in keys)])
    if well_type and asset_id:
        return _result(kind, [], [], ["give well_type or asset_id, not both"])
    if asset_id and not db.rows("SELECT 1 FROM wells WHERE asset_id = ?", (asset_id,)):
        return _result(kind, [], [], [f"unknown well '{asset_id}'"])
    types = [r["well_type"] for r in db.rows("SELECT DISTINCT well_type FROM wells ORDER BY well_type")]
    if well_type and well_type not in types:
        return _result(kind, [], [], [f"unknown well_type '{well_type}'; valid: {', '.join(types)}"])

    scope = f"well {asset_id}" if asset_id else f"all {well_type} wells" if well_type else "all wells"
    in_scope = ("w.asset_id = :a" if asset_id else "w.well_type = :t" if well_type else "1")
    scope_args = {"a": asset_id, "t": well_type}
    before = db.rows(
        f"""SELECT DISTINCT r.value, r.rule_id FROM well_rules r JOIN wells w ON w.asset_id = r.asset_id
            WHERE r.rule_key = :k AND {in_scope}""", {"k": rule_key, **scope_args})

    with closing(db.connect(read_only=False)) as conn, conn:
        conn.execute(
            "UPDATE rules SET status = 'superseded' WHERE source = 'user' AND status = 'active' AND rule_key = ? "
            "AND well_type IS ? AND asset_id IS ?", (rule_key, well_type, asset_id))
        rule_id = conn.execute(
            """INSERT INTO rules (rule_key, well_type, asset_id, value, unit, source, author_user_id, reason,
                   created_at, conversation_id)
               VALUES (?, ?, ?, ?, ?, 'user', ?, ?, ?, ?)""",
            (rule_key, well_type, asset_id, value, unit, profile["user_id"], reason, _stamp(), thread_id)).lastrowid

    cite = user_rule_cite(rule_id, profile["user_id"])
    was = "; ".join(f"{b['value']:g} from {_cite(b['rule_id'])}" for b in before) or "no rule"
    n = db.rows(f"SELECT COUNT(*) AS n FROM wells w WHERE {in_scope}", scope_args)[0]["n"]
    values = _rule_values(rule_key)
    keep = [v for v in values if v["rule_id"] != rule_id]
    notes = [f"recorded {cite}: {rule_key} = {value:g} {unit or ''} for {scope} ({n} wells); was {was}"]
    if keep:
        notes.append("other wells keep their rule: " + "; ".join(_describe(v) for v in keep))
    row = {"rule_id": rule_id, "rule_key": rule_key, "value": value, "unit": unit, "scope": scope,
           "well_type": well_type, "asset_id": asset_id, "wells_in_scope": n, "set_by": profile["name"],
           "reason": reason, "previous": was}
    return _result(kind, [row], [cite, *[_cite(b["rule_id"]) for b in before]], notes)


FEEDBACK_TOOLS = [record_correction, add_note, set_rule]
