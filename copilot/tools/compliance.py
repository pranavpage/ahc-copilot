"""Operations SOP rev 2 (OPS-1, OPS-2, OPS-5), the regulator's spill letter, waiting reasons, teams.

The rules are applied here, in Python, so the model only has to present the rows.
Timestamps in the data are UTC ISO strings ("2026-12-03T12:10:00Z"). Dates are YYYY-MM-DD.
`area` is a name ("Northeast Block 8") or an ID ("NE-08").
"""

import re
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from copilot import db
from copilot.tools.base import ToolResult
from copilot.tools.records import _date_note, _empty, _resolve_area, _result

OPS = "operations-sop-rev2"
CITE_OPS1 = f"{OPS} §OPS-1 Gas odor response"
CITE_OPS2 = f"{OPS} §OPS-2 Temporary bypass"
CITE_OPS5 = f"{OPS} §OPS-5 Freeze protection (1 Dec – 28 Feb)"
CITE_SR_CLASSES = "spill-response-sop §3. Spill classes"
CITE_SR_FALSE = "spill-response-sop §7. False positives"
CITE_LETTER = "regulator-letter-2026-11-20 §Letter from the State Oil & Gas Commission"

OPS1_CUTOVER = "2027-01-01"           # 24 h before this date, 12 h from it
LETTER_AREAS = ("NE-07", "NE-08")
LETTER_SINCE = "2026-06-01"
LETTER_DEADLINE = "2027-01-15"
SOIL_SENTENCE = "Soil samples sent to the lab."
FREEZE_MAX_C = -5.0
FREEZE_DAYS = 7
WAIT_LABELS = {"parts": "parts", "crew": "crews", "contractor": "contractors",
               "weather": "weather", "rig": "workover rig", "other": "other"}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _now() -> datetime:
    """End of 'today' (the data runs up to today), UTC."""
    return datetime.fromisoformat(db.today()).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _hours(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 3600, 1)


def _area_filter(area: str | None) -> tuple[str | None, str | None]:
    """(area_id or None, error note or None)."""
    if not area:
        return None, None
    return _resolve_area(area)


def _area_names() -> dict[str, str]:
    return {r["area_id"]: r["name"] for r in db.rows("SELECT area_id, name FROM areas")}


# ----------------------------------------------------------------------------
# OPS-1 gas odor response
# ----------------------------------------------------------------------------

def gas_reports(start: str, end: str | None = None, area: str | None = None,
                asset_id: str | None = None) -> ToolResult:
    """Every operator note reporting gas (gas odor, rotten-egg smell, H2S alarm) written between
    start and end (inclusive, default today), and whether a field response met the OPS-1 deadline.

    Rule (Operations SOP rev 2, OPS-1): the response is the FIRST maintenance job on that well
    (started_at) or MANUAL inspection of that well (drone inspections do not count) that starts
    after the note's created_at. Deadline 24 h for notes before 1 Jan 2027, 12 h from 1 Jan 2027.
    Also answers "what was the H2S reading" for a gas report: `h2s_max_ppm` is the highest
    personal-monitor reading in the response job's repair report (WS-03); no response = no
    reading was taken after the report. Filter one well with asset_id.
    result: Met | Missed (no response, or later than the deadline) | Pending (no response yet
    and the deadline has not passed today).
    One row per report: asset_id, area, note_id, reported_at, note_text, response_id,
    response_kind, response_at, hours_to_response, deadline_hours, result.
    """
    kind = "gas_reports"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    area_id, note = _area_filter(area)
    if note:
        return _empty(kind, note)

    found = db.rows("""
        SELECT n.note_id, n.asset_id, n.created_at, n.text, a.name AS area
        FROM notes n JOIN wells w ON w.asset_id = n.asset_id
        LEFT JOIN areas a ON a.area_id = w.area_id
        WHERE n.event = 'gas_odor' AND substr(n.created_at, 1, 10) >= :start
          AND (:end IS NULL OR substr(n.created_at, 1, 10) <= :end)
          AND (:area_id IS NULL OR w.area_id = :area_id)
          AND (:asset_id IS NULL OR n.asset_id = :asset_id)
        ORDER BY n.created_at, n.asset_id""", {"start": start, "end": end, "area_id": area_id, "asset_id": asset_id})

    now = _now()
    rows, ids = [], [CITE_OPS1]
    for n in found:
        created = _ts(n["created_at"])
        deadline = 24 if n["created_at"][:10] < OPS1_CUTOVER else 12
        resp = db.rows("""
            SELECT * FROM (
                SELECT maintenance_id AS id, 'maintenance job' AS kind, started_at AS at,
                       issue AS what FROM maintenance WHERE asset_id = :a AND started_at > :t
                UNION ALL
                SELECT inspection_id, 'manual inspection', inspected_at, notes FROM inspections
                WHERE asset_id = :a AND method = 'manual' AND inspected_at > :t)
            ORDER BY at, id LIMIT 1""", {"a": n["asset_id"], "t": n["created_at"]})
        row = {"asset_id": n["asset_id"], "area": n["area"], "note_id": n["note_id"],
               "reported_at": _fmt(created), "note_text": n["text"],
               "response_id": None, "response_kind": None, "response_at": None,
               "hours_to_response": None, "deadline_hours": deadline}
        if resp:
            r = resp[0]
            hours = _hours(created, _ts(r["at"]))
            h2s = db.rows("SELECT h2s_max_ppm FROM maintenance_reports WHERE maintenance_id = ?", (r["id"],))
            row |= {"response_id": r["id"], "response_kind": r["kind"], "response_at": _fmt(_ts(r["at"])),
                    "hours_to_response": hours, "h2s_max_ppm": h2s[0]["h2s_max_ppm"] if h2s else None}
            row["result"] = "Met" if hours <= deadline else "Missed"
            ids.append(r["id"])
        else:
            row["response_id"] = "none"
            row["h2s_max_ppm"] = None
            row["h2s_note"] = "no field response after the report, so no H2S reading was taken"
            row["result"] = "Pending" if created + timedelta(hours=deadline) > now else "Missed"
        rows.append(row)
        ids.append(n["note_id"])

    counts = {k: sum(r["result"] == k for r in rows) for k in ("Met", "Missed", "Pending")}
    notes = [
        "OPS-1 (Operations SOP rev 2): first maintenance job (started_at) or MANUAL inspection on the "
        "well after the note's created_at; drone inspections do not count; deadline 24 h for notes "
        "before 2027-01-01, 12 h from 2027-01-01. Times are UTC.",
        f"{len(rows)} gas reports: {counts['Met']} Met, {counts['Missed']} Missed, {counts['Pending']} Pending.",
    ]
    if not rows:
        notes.append("no gas reports in the window")
    return _result(kind, rows, ids, notes)


# ----------------------------------------------------------------------------
# OPS-2 temporary bypass
# ----------------------------------------------------------------------------

def bypasses(area: str | None = None) -> ToolResult:
    """Every temporary flowline bypass, past and present, and whether it is allowed (OPS-2).

    A bypass runs from a well's `bypass_in` operator note to its next `bypass_out` note (no out
    note = still in). It is allowed only on a well named in a management-of-change memo
    (moc-*.md) that has not expired; an extension memo replaces the expiry date (MOC-2026-044
    extends MOC-2026-031 to 28 Feb 2027). Expiry is the end of that day.
    status: Allowed | Expired (still in after the expiry date, including still in today, or
    removed after it) | Not approved (well named in no MOC, or put in before the memo took
    effect). in_place_now = still in today. For "which bypasses are in place now" filter
    in_place_now; for violations take status != Allowed.
    Columns: asset_id, area, bypass_in_note_id, bypass_in, bypass_out_note_id, bypass_out,
    moc_id, approval_valid_until, status, in_place_now, detail.
    """
    kind = "bypasses"
    area_id, note = _area_filter(area)
    if note:
        return _empty(kind, note)

    found = db.rows("""
        SELECT n.note_id, n.asset_id, n.created_at, n.event, a.name AS area
        FROM notes n JOIN wells w ON w.asset_id = n.asset_id
        LEFT JOIN areas a ON a.area_id = w.area_id
        WHERE n.event IN ('bypass_in', 'bypass_out') AND (:area_id IS NULL OR w.area_id = :area_id)
        ORDER BY n.asset_id, n.created_at, n.note_id""", {"area_id": area_id})
    mocs: dict[str, list[dict]] = {}
    for m in db.rows("SELECT * FROM moc_approvals ORDER BY effective_from"):
        mocs.setdefault(m["asset_id"], []).append(m)

    # Pair each bypass_in with the next bypass_out on the same well.
    pairs: list[dict] = []
    open_by_well: dict[str, dict] = {}
    for n in found:
        if n["event"] == "bypass_in":
            if n["asset_id"] in open_by_well:   # second "in" without an "out": keep the first one open
                continue
            open_by_well[n["asset_id"]] = p = {"in": n, "out": None}
            pairs.append(p)
        elif n["asset_id"] in open_by_well:
            open_by_well.pop(n["asset_id"])["out"] = n

    today = db.today()
    rows, ids = [], [CITE_OPS2]
    for p in pairs:
        n_in, n_out = p["in"], p["out"]
        well = n_in["asset_id"]
        d_in = n_in["created_at"][:10]
        d_out = n_out["created_at"][:10] if n_out else None
        in_now = n_out is None
        # Pick the memo covering the well; prefer one in force on the bypass_in date.
        cands = mocs.get(well, [])
        moc = next((m for m in cands if m["effective_from"] <= d_in <= m["expires_on"]), None) \
            or (cands[-1] if cands else None)
        row = {"asset_id": well, "area": n_in["area"], "bypass_in_note_id": n_in["note_id"],
               "bypass_in": d_in, "bypass_out_note_id": n_out["note_id"] if n_out else None,
               "bypass_out": d_out or "still in", "moc_id": moc["moc_id"] if moc else None,
               "approval_valid_until": moc["expires_on"] if moc else None}
        if not moc:
            status, detail = "Not approved", f"{well} is not named in any MOC memo"
        else:
            exp = moc["expires_on"]
            ext = f" (extended by {moc['extended_by']}, was {moc['original_expiry']})" if moc["extended_by"] else ""
            if d_in < moc["effective_from"]:
                status, detail = "Not approved", f"put in {d_in}, before {moc['moc_id']} took effect on {moc['effective_from']}"
            elif d_in > exp:
                status, detail = "Expired", f"put in {d_in}, after {moc['moc_id']} expired on {exp}"
            elif in_now and today > exp:
                status, detail = "Expired", f"still in today ({today}); {moc['moc_id']} expired end of {exp}{ext}"
            elif not in_now and d_out > exp:
                status, detail = "Expired", f"removed {d_out}, after {moc['moc_id']} expired end of {exp}{ext}"
            else:
                status = "Allowed"
                detail = (f"still in, within {moc['moc_id']} valid until {exp}{ext}" if in_now
                          else f"removed {d_out}, within {moc['moc_id']} valid until {exp}{ext}")
            ids += [moc["moc_id"], moc["extended_by"]]
        row |= {"status": status, "in_place_now": in_now, "detail": detail}
        rows.append(row)
        ids += [n_in["note_id"], n_out["note_id"] if n_out else None]

    named_unused = sorted(w for w in mocs if w not in {p["in"]["asset_id"] for p in pairs}
                          and (area_id is None or w in _wells_in_area(area_id)))
    now_in = [r for r in rows if r["in_place_now"]]
    bad = [r for r in rows if r["status"] != "Allowed"]
    notes = [
        "OPS-2 (Operations SOP rev 2): a bypass runs from its bypass_in operator note to the next "
        "bypass_out note; allowed only on a well named in an unexpired MOC; an extension memo replaces "
        "the expiry (MOC-2026-044 extends MOC-2026-031 to 2027-02-28); expiry = end of that day; a bypass "
        "still in after expiry (incl. today) or removed after expiry is Expired; a well in no MOC is Not "
        "approved. Judgement: a bypass put in before the memo's 'Effective from' date counts as Not approved "
        "(no bypass in the data hits this).",
        f"{len(rows)} bypasses: {len(now_in)} in place now "
        f"({', '.join(f'{r['asset_id']} {r['status']}' for r in now_in) or 'none'}); "
        f"{len(bad)} violations ({', '.join(f'{r['asset_id']} {r['status']}' for r in bad) or 'none'}).",
    ]
    if named_unused:
        notes.append(f"named in a MOC but no bypass notes: {', '.join(named_unused)}")
    return _result(kind, rows, ids, notes)


def _wells_in_area(area_id: str) -> set[str]:
    return {r["asset_id"] for r in db.rows("SELECT asset_id FROM wells WHERE area_id = ?", (area_id,))}


# ----------------------------------------------------------------------------
# Regulator letter (20 Nov 2026): soil samples after reportable spills
# ----------------------------------------------------------------------------

def regulator_letter_spills(area: str | None = None) -> ToolResult:
    """Spills covered by the State Oil & Gas Commission letter of 20 Nov 2026, and compliance.

    Covered: every REPORTABLE spill (5 bbl or more, Spill Response SOP §3, volume after any
    data_correction) in Northeast Block 7 or Northeast Block 8 discovered from 1 Jun 2026 up to
    today; spills confirmed as not crude oil (correction notes) are excluded.
    Compliant only if the clean-up report (the maintenance job triggered by the spill
    inspection) contains the sentence "Soil samples sent to the lab." (HSE note, 22 Nov 2026).
    Field soil readings (TPH results on site) do not count; no clean-up job or report = No.
    Columns: asset_id, area, inspection_id, inspected_date, volume_bbl, cleanup_job,
    compliant (Yes/No), reason. `area` narrows to one of the two letter areas.
    """
    kind = "regulator_letter_spills"
    area_id, note = _area_filter(area)
    if note:
        return _empty(kind, note)
    areas = [a for a in LETTER_AREAS if area_id in (None, a)]
    if not areas:
        return _empty(kind, f"the letter covers only Northeast Block 7 and Northeast Block 8, not '{area}'")
    names = _area_names()
    today = db.today()
    p = {"since": LETTER_SINCE, "today": today}
    in_areas = "(" + ",".join(f"'{a}'" for a in areas) + ")"

    found = db.rows(f"""
        SELECT s.inspection_id, s.asset_id, s.area_id, s.inspected_date, s.spill_volume_bbl,
               s.raw_spill_est_volume_bbl, s.is_reportable, s.correction_ids
        FROM spills s
        WHERE s.area_id IN {in_areas} AND s.inspected_date >= :since AND s.inspected_date <= :today
        ORDER BY s.inspected_at, s.asset_id""", p)
    # one row per spill (a spill can have several triggered jobs)
    seen: dict[str, dict] = {}
    for s in found:
        seen.setdefault(s["inspection_id"], s)

    rows, ids = [], [CITE_LETTER, CITE_SR_CLASSES, CITE_SR_FALSE]
    not_crude: list[str] = []
    for s in seen.values():
        if not s["is_reportable"]:
            continue
        fb = _not_crude_feedback(s["inspection_id"])
        if fb:
            not_crude.append(f"{s['inspection_id']} ({fb})")
            ids.append(fb)
            continue
        jobs = db.rows("""
            SELECT m.maintenance_id, r.maintenance_id AS report_id, r.soil_samples_sent, r.is_interim,
                   r.file_path
            FROM maintenance m LEFT JOIN maintenance_reports r ON r.maintenance_id = m.maintenance_id
            WHERE m.triggered_by_inspection_id = ? ORDER BY m.started_at""", (s["inspection_id"],))
        row = {"asset_id": s["asset_id"], "area": names.get(s["area_id"]), "inspection_id": s["inspection_id"],
               "inspected_date": s["inspected_date"], "volume_bbl": s["spill_volume_bbl"]}
        if s["correction_ids"]:
            row["volume_note"] = f"corrected from {s['raw_spill_est_volume_bbl']} bbl ({s['correction_ids']})"
            ids += s["correction_ids"].split()
        if not jobs:
            row |= {"cleanup_job": "none", "compliant": "No", "reason": "no clean-up job recorded"}
        else:
            sent = [j for j in jobs if j["soil_samples_sent"]]
            job = sent[0] if sent else jobs[0]
            row["cleanup_job"] = job["maintenance_id"]
            ids.append(job["maintenance_id"])
            if sent:
                row |= {"compliant": "Yes", "reason": f'clean-up report says "{SOIL_SENTENCE}"'}
            elif not job["report_id"]:
                row |= {"compliant": "No", "reason": "no clean-up report for the job"}
            else:
                extra = " (interim report, job still in progress)" if job["is_interim"] else ""
                row |= {"compliant": "No",
                        "reason": f'clean-up report has no "{SOIL_SENTENCE}"; only field soil readings '
                                  f"(TPH on site), which do not count{extra}"}
        rows.append(row)
        ids.append(s["inspection_id"])

    nos = [r for r in rows if r["compliant"] == "No"]
    near = [s for s in seen.values() if not s["is_reportable"] and (s["spill_volume_bbl"] or 0) >= 4]
    notes = [
        "Covered: reportable spills (>= 5 bbl, Spill Response SOP §3, after data corrections) in "
        "Northeast Block 7 / Northeast Block 8 discovered from 2026-06-01 to today; spills confirmed as not "
        "crude oil are excluded (correction notes cancel the detection; operator_feedback saying 'not crude' "
        "is ignored when a later note says the detection stands). Compliant only if the clean-up report "
        f'contains "{SOIL_SENTENCE}" (HSE internal note on the letter); field soil readings do not count.',
        f"{len(rows)} spills covered: {len(rows) - len(nos)} compliant, {len(nos)} not compliant "
        f"({', '.join(r['asset_id'] + ' ' + r['inspection_id'] for r in nos) or 'none'}). "
        f"Results are due {LETTER_DEADLINE}; spills found up to today are included.",
        "The only volume correction that crosses 5 bbl (INS-0067-0216, 4.8 -> 5.6 bbl) is on WELL-0067 in "
        "Southwest Block 24, outside the letter's areas.",
    ]
    if near:
        notes.append("not covered, below 5 bbl: " + ", ".join(
            f"{s['inspection_id']} {s['spill_volume_bbl']} bbl" for s in near))
    if not_crude:
        notes.append("excluded as not crude oil: " + ", ".join(not_crude))
    return _result(kind, rows, ids, notes)


def _not_crude_feedback(inspection_id: str) -> str | None:
    """note_id of the latest operator_feedback note on the inspection if it says 'not crude'."""
    fb = db.rows("""SELECT note_id, text FROM notes WHERE note_type = 'operator_feedback'
                    AND text LIKE '%' || ? || '%' ORDER BY created_at DESC LIMIT 1""", (inspection_id,))
    if not fb:
        return None
    text = fb[0]["text"].lower()
    if "not crude" in text and "stands" not in text and "it is crude" not in text:
        return fb[0]["note_id"]
    return None


# ----------------------------------------------------------------------------
# OPS-5 freeze protection
# ----------------------------------------------------------------------------

def _in_freeze_season(d: str) -> bool:
    m, day = int(d[5:7]), int(d[8:10])
    return m in (12, 1) or (m == 2 and day <= 28)


def freeze_checks(start: str, end: str, area: str | None = None, missed_only: bool = False) -> ToolResult:
    """Cold-weather heat trace checks (Operations SOP rev 2, OPS-5) for readings between start and end.

    Rule: from 1 Dec to 28 Feb, an inspection with ambient_temp_c at or below -5 °C on a well
    that is producing oil at that reading needs a maintenance job whose issue contains
    "Heat trace check" on that well, starting within 7 days after the inspection. Cold readings
    on wells not producing need no check.
    One row per cold producing reading: asset_id, area, inspection_id, inspected_at,
    ambient_temp_c, check_job, check_started_at, days_to_check, result (Met | Missed | Pending:
    no check yet and the 7 days have not passed today). missed_only=True keeps the Missed rows.
    """
    kind = "freeze_checks"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    area_id, note = _area_filter(area)
    if note:
        return _empty(kind, note)

    found = db.rows("""
        SELECT e.inspection_id, e.asset_id, e.inspected_at, e.inspected_date, e.ambient_temp_c,
               e.temp_delta_c, e.producing_threshold_c, a.name AS area
        FROM inspections_effective e LEFT JOIN areas a ON a.area_id = e.area_id
        WHERE e.inspected_date BETWEEN :start AND :end AND e.ambient_temp_c <= :cold
          AND e.is_producing = 1 AND (:area_id IS NULL OR e.area_id = :area_id)
        ORDER BY e.inspected_at, e.asset_id""",
        {"start": start, "end": end, "cold": FREEZE_MAX_C, "area_id": area_id})
    checks: dict[str, list[dict]] = {}
    for m in db.rows("""SELECT maintenance_id, asset_id, started_at FROM maintenance
                        WHERE issue LIKE '%Heat trace check%' ORDER BY started_at"""):
        checks.setdefault(m["asset_id"], []).append(m)

    now = _now()
    rows, ids = [], [CITE_OPS5]
    for r in found:
        if not _in_freeze_season(r["inspected_date"]):
            continue
        t = _ts(r["inspected_at"])
        due = t + timedelta(days=FREEZE_DAYS)
        job = next((m for m in checks.get(r["asset_id"], []) if _ts(m["started_at"]) > t), None)
        row = {"asset_id": r["asset_id"], "area": r["area"], "inspection_id": r["inspection_id"],
               "inspected_at": _fmt(t), "ambient_temp_c": r["ambient_temp_c"],
               "check_job": None, "check_started_at": None, "days_to_check": None}
        if job and _ts(job["started_at"]) <= due:
            days = round((_ts(job["started_at"]) - t).total_seconds() / 86400, 1)
            row |= {"check_job": job["maintenance_id"], "check_started_at": _fmt(_ts(job["started_at"])),
                    "days_to_check": days, "result": "Met"}
            ids.append(job["maintenance_id"])
        else:
            if job:   # a later check exists, but too late
                days = round((_ts(job["started_at"]) - t).total_seconds() / 86400, 1)
                row |= {"check_job": job["maintenance_id"], "check_started_at": _fmt(_ts(job["started_at"])),
                        "days_to_check": days}
                ids.append(job["maintenance_id"])
            row["result"] = "Pending" if (due > now and not job) else "Missed"
        rows.append(row)
        ids.append(r["inspection_id"])

    counts = {k: sum(r["result"] == k for r in rows) for k in ("Met", "Missed", "Pending")}
    if missed_only:
        rows = [r for r in rows if r["result"] == "Missed"]
    notes = [
        "OPS-5 (Operations SOP rev 2): 1 Dec - 28 Feb, a reading with ambient <= -5 °C on a well producing at "
        "that reading (inspections_effective.is_producing) needs a job whose issue contains 'Heat trace check' "
        "starting within 7 days after the inspection. Readings on non-producing wells need no check.",
        f"{sum(counts.values())} cold producing readings: {counts['Met']} Met, {counts['Missed']} Missed, "
        f"{counts['Pending']} Pending.",
    ]
    if not rows:
        notes.append("no rows match")
    return _result(kind, rows, ids, notes)


# ----------------------------------------------------------------------------
# Waiting reasons (shut in longer than the repair)
# ----------------------------------------------------------------------------

RIG_WAIT = re.compile(
    r"(The company|(?P<owner>[A-Z][^.]*?)'s) workover rig was busy on other wells, so the well waited about "
    r"(?P<days>\d+(?:\.\d+)?) days? for it")


def waiting_reasons(start: str, end: str, area: str | None = None,
                    include_interim: bool = False) -> ToolResult:
    """What repairs waited on when the well stayed shut in longer than the repair itself.

    For jobs STARTED between start and end (inclusive), from two report sentences:
    - "The well stayed shut in for about N days longer than the repair itself because ..."
      (parts back-ordered, crew committed elsewhere, weekday contractor slot, rain/weather), and
    - "<owner>'s workover rig was busy on other wells, so the well waited about N days for it".
    A busy company rig counts as crews and a busy contractor's rig as contractors, so every wait
    falls in one of the four reasons asked about: parts, crews, contractors, weather.
    Interim reports ("expected to stay shut in", job still in progress) are excluded unless
    include_interim=True.
    One row per area x reason (plus area = "All areas"): area, reason, jobs, share_pct (of that
    area's waiting jobs; use for a stacked bar chart), typical_extra_days (median),
    mean_extra_days. Notes name the area that stands out against the field-wide shares.
    """
    kind = "waiting_reasons"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    rig = "by_owner"
    area_id, note = _area_filter(area)
    if note:
        return _empty(kind, note)

    reports = db.rows("""
        SELECT m.maintenance_id, m.asset_id, m.contractor, a.name AS area, r.wait_extra_days,
               r.wait_reason, r.is_interim, r.body_md
        FROM maintenance_reports r JOIN maintenance m ON m.maintenance_id = r.maintenance_id
        JOIN wells w ON w.asset_id = m.asset_id LEFT JOIN areas a ON a.area_id = w.area_id
        WHERE substr(m.started_at, 1, 10) BETWEEN :start AND :end
          AND (:area_id IS NULL OR w.area_id = :area_id)
          AND (r.wait_reason IS NOT NULL OR r.body_md LIKE '%workover rig was busy%')
        ORDER BY a.name, m.started_at""", {"start": start, "end": end, "area_id": area_id})

    found: list[dict] = []
    for r in reports:
        if r["wait_reason"]:
            reason, days, owner = r["wait_reason"], r["wait_extra_days"], r["contractor"]
        else:
            m = RIG_WAIT.search(r["body_md"])
            if not m:
                continue
            reason, days, owner = "rig", float(m.group("days")), m.group("owner")
        if reason == "rig":
            label = "workover rig" if rig == "separate" else ("contractors" if owner else "crews")
        else:
            label = WAIT_LABELS.get(reason, reason)
        found.append({**r, "label": label, "days": days, "rig_wait": reason == "rig"})
    interim_skipped = [r for r in found if r["is_interim"] and not include_interim]
    found = [r for r in found if include_interim or not r["is_interim"]]

    groups: dict[str, dict[str, list[float]]] = {}
    for r in found:
        for a in (r["area"], "All areas"):
            groups.setdefault(a, {}).setdefault(r["label"], []).append(r["days"])

    order = ["parts", "crews", "contractors", "weather", "workover rig", "other"]
    rows = []
    areas = sorted(a for a in groups if a != "All areas") + (["All areas"] if groups else [])
    for a in areas:
        total = sum(len(v) for v in groups[a].values())
        for reason in sorted(groups[a], key=lambda x: order.index(x) if x in order else 99):
            days = groups[a][reason]
            rows.append({"area": a, "reason": reason, "jobs": len(days),
                         "share_pct": round(100 * len(days) / total, 1),
                         "typical_extra_days": median(days), "mean_extra_days": round(mean(days), 1)})

    n_rig = sum(r["rig_wait"] for r in found)
    rig_note = ("a busy workover rig is counted by its owner: the company rig -> crews, a contractor's rig "
                "(e.g. Sandstone Rod & Pump, Coyote Ridge Well Services) -> contractors"
                if rig == "by_owner" else "a busy workover rig is kept as its own reason 'workover rig'")
    notes = [
        "From repair reports, jobs started " f"{start} to {end}: 'stayed shut in for about N days longer than "
        "the repair itself because ...' (parts back-ordered -> parts, crew on another job -> crews, weekday "
        "contractor slot -> contractors, rain -> weather) and '<owner>'s workover rig was busy on other wells, "
        f"so the well waited about N days for it' ({n_rig} jobs); judgement: {rig_note}. "
        "typical = median extra days.",
        f"{len(found)} waiting jobs." + (
            f" Excluded {len(interim_skipped)} interim reports (job still in progress; the well 'is expected to "
            "stay shut in', not a final figure)." if interim_skipped else ""),
    ]
    summary = []
    for a in areas:
        days = [d for v in groups[a].values() for d in v]
        top = max((r for r in rows if r["area"] == a), key=lambda r: r["share_pct"])
        summary.append(f"{a}: {len(days)} jobs, typical {median(days)} d, top {top['reason']} {top['share_pct']}%")
    notes.append("By area: " + "; ".join(summary) + ".")
    notes += _stand_out(rows)
    ids = sorted({r["maintenance_id"] for r in found})
    # ids for citations: cap so the result stays small; the rows carry the aggregates
    return _result(kind, rows, ids[:50], notes)


def _stand_out(rows: list[dict]) -> list[str]:
    field = {r["reason"]: r for r in rows if r["area"] == "All areas"}
    if not field:
        return []
    best = None
    for r in rows:
        if r["area"] == "All areas":
            continue
        gap = r["share_pct"] - field[r["reason"]]["share_pct"]
        if best is None or abs(gap) > abs(best[0]):
            best = (gap, r)
    out = []
    if best:
        gap, r = best
        f = field[r["reason"]]
        out.append(f"Stands out (share): {r['area']} - {r['reason']} is {r['share_pct']}% of its waiting jobs vs "
                   f"{f['share_pct']}% field-wide ({gap:+.1f} points); typical {r['typical_extra_days']} extra "
                   f"days vs {f['typical_extra_days']} field-wide.")
    best_d = None
    for r in rows:
        if r["area"] == "All areas" or r["jobs"] < 5:
            continue
        gap = r["typical_extra_days"] - field[r["reason"]]["typical_extra_days"]
        if best_d is None or abs(gap) > abs(best_d[0]):
            best_d = (gap, r)
    if best_d and abs(best_d[0]) >= 2:
        gap, r = best_d
        out.append(f"Stands out (days): {r['area']} - {r['reason']} typical {r['typical_extra_days']} extra days vs "
                   f"{field[r['reason']]['typical_extra_days']} field-wide.")
    return out


# ----------------------------------------------------------------------------
# Teams
# ----------------------------------------------------------------------------

def team_summary(team: str) -> ToolResult:
    """Who leads a production team and how many wells it runs, by area.

    `team` is a name ("Northwest Production") or ID ("TEAM-NW"). The lead is teams.lead_user_id
    (else the team's production supervisor). A well belongs to the team by its own current
    team_id, which takes priority over its area's team (one area can have wells of two teams).
    Plugged-and-abandoned wells are not counted as run, but reported separately.
    One row per area: team, lead, area, wells_run, plugged; plus an "All areas" total row.
    """
    kind = "team_summary"
    found = db.rows("""SELECT * FROM teams WHERE team_id = :t OR lower(name) = lower(:t)
                       OR lower(name) LIKE lower(:t) || '%'""", {"t": team.strip()})
    if not found:
        names = [r["name"] for r in db.rows("SELECT name FROM teams ORDER BY name")]
        return _empty(kind, f"unknown team '{team}'; valid: {', '.join(names)}")
    t = found[0]
    lead = db.rows("SELECT user_id, name, role FROM users WHERE user_id = ?", (t["lead_user_id"],)) \
        if t["lead_user_id"] else []
    basis = "teams.lead_user_id"
    if not lead:
        lead = db.rows("""SELECT user_id, name, role FROM users WHERE team_id = ?
                          AND role = 'production_supervisor' ORDER BY user_id LIMIT 1""", (t["team_id"],))
        basis = "the team's production supervisor (no lead_user_id)"
    lead_name = lead[0]["name"] if lead else None
    lead_id = lead[0]["user_id"] if lead else None

    by_area = db.rows("""
        SELECT w.area_id, a.name AS area, a.team_id AS area_team,
               SUM(COALESCE(w.status, '') <> 'plugged_and_abandoned') AS wells_run,
               SUM(COALESCE(w.status, '') = 'plugged_and_abandoned') AS plugged
        FROM wells w LEFT JOIN areas a ON a.area_id = w.area_id
        WHERE w.team_id = ? GROUP BY w.area_id ORDER BY a.name""", (t["team_id"],))
    base = {"team_id": t["team_id"], "team": t["name"], "lead_user_id": lead_id, "lead": lead_name}
    rows = [base | {"area": r["area"], "wells_run": r["wells_run"], "plugged": r["plugged"]} for r in by_area]
    total = sum(r["wells_run"] for r in by_area)
    plugged = sum(r["plugged"] for r in by_area)
    if rows:
        rows.append(base | {"area": "All areas", "wells_run": total, "plugged": plugged})

    others = db.rows("""
        SELECT a.name AS area, w.team_id, COUNT(*) AS n FROM wells w JOIN areas a ON a.area_id = w.area_id
        WHERE a.team_id = ? AND w.team_id <> ? AND (w.status IS NULL OR w.status <> 'plugged_and_abandoned')
        GROUP BY 1, 2""", (t["team_id"], t["team_id"]))
    notes = [
        f"{t['name']} ({t['team_id']}) is led by {lead_name} ({lead_id}), from {basis}.",
        f"It runs {total} wells (by each well's own current team_id, which beats the area's team; "
        f"plugged-and-abandoned wells excluded: {plugged}).",
    ]
    for o in others:
        notes.append(f"{o['n']} wells in {o['area']} (this team's area) are run by {o['team_id']}, not counted.")
    return _result(kind, rows, [t["team_id"], lead_id], notes)


COMPLIANCE_TOOLS = [gas_reports, bypasses, regulator_letter_spills, freeze_checks, waiting_reasons, team_summary]
