"""Recalled pumps, status conflicts (OPS-3), operator concerns, field temperature, data coverage.

The rules are applied here, in Python, so the model only has to present the rows.
Timestamps in the data are UTC ISO strings. Dates are YYYY-MM-DD.
`area` is a name ("Northwest Block 12") or an ID ("NW-12").
"""

import json
from statistics import mean

from copilot import db
from copilot.tools.base import ToolResult
from copilot.tools.records import _date_note, _empty, _resolve_area, _result

OPS = "operations-sop-rev2"
CITE_OPS3 = f"{OPS} §OPS-3 Status evidence precedence"
CITE_RECALL = "supplier-recall-notice-2026-12-01 §What is recalled"
CITE_T500 = "T500 §5. Early warning signs"

# Operator-note symptoms, by how strongly they point to a failure soon (judgement, stated in notes).
SYMPTOM_WEIGHT = {"drive tripping": 3.0, "leak": 3.0, "amps hunting": 2.5, "fluid pound": 2.0,
                  "tagging bottom": 2.0, "rattle": 1.5, "rod squeal": 1.0}


def _area(area: str | None) -> tuple[str | None, str | None]:
    return _resolve_area(area) if area else (None, None)


def _months_before(today: str, months: int) -> str:
    return db.rows("SELECT date(?, ?) AS d", (today, f"-{months} months"))[0]["d"]


def _user_reports(asset_ids: list[str]) -> dict[str, list[dict]]:
    """What users told the copilot about these wells (notes with source = 'copilot')."""
    out: dict[str, list[dict]] = {}
    for n in db.rows("""
        SELECT n.asset_id, n.note_id, u.name AS reported_by, n.created_at, n.claim_status, n.text
        FROM notes n LEFT JOIN users u ON u.user_id = n.author_user_id
        WHERE n.source = 'copilot' AND COALESCE(n.claim_status, '') <> 'retracted'
          AND n.asset_id IN (SELECT value FROM json_each(:ids))
        ORDER BY n.created_at""", {"ids": json.dumps(asset_ids)}):
        out.setdefault(n.pop("asset_id"), []).append(n)
    return out


def _last_repairs(asset_ids: list[str], today: str) -> dict[str, dict]:
    out = {}
    for m in db.rows("""
        SELECT asset_id, maintenance_id, substr(started_at, 1, 10) AS date, maintenance_type,
               equipment_kind, issue
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY asset_id ORDER BY started_at DESC) AS rn
              FROM maintenance
              WHERE asset_id IN (SELECT value FROM json_each(:ids)) AND substr(started_at, 1, 10) <= :today
                AND issue NOT LIKE 'Heat trace check%')
        WHERE rn = 1""", {"ids": json.dumps(asset_ids), "today": today}):
        out[m.pop("asset_id")] = m
    return out


RECENT_NOTE_DAYS = 30

STATUS_LABEL = {"producing": "Producing oil", "not_producing": "Not producing oil",
                "producing_unconfirmed": "Producing oil (unconfirmed)", "plugged": "Plugged and abandoned"}


# ----------------------------------------------------------------------------
# Recall notice
# ----------------------------------------------------------------------------

def recalled_pumps(area: str | None = None, include_replaced: bool = False) -> ToolResult:
    """Recalled downhole pumps still in the ground right now (supplier recall notice of
    1 Dec 2026: Highline RP-175 pumps from lots LOT-2409-A, LOT-2409-C, LOT-2410-B).

    The pump in a well is the one from its LATEST "Parts installed" line (repair reports); a
    recalled pump that was later pulled and replaced does not count. Plugged wells and ESP (T500)
    wells are left out. One row per well: asset_id, area, team_id, install_job, installed_on,
    pump_model, serial, lot, install_cost_usd (the install job's total; also parts and labor),
    status_now (OPS-3), last_repair, replace_by (31 Dec 2026), overdue, and `user_reports`: what
    users told the copilot about the well (e.g. "pump swapped"). A user report is NOT a work
    order: keep the well in the list and show the report next to it, with who said it and when.
    include_replaced=True also lists recalled pumps already replaced, and the job that did it.
    """
    kind = "recalled_pumps"
    area_id, note = _area(area)
    if note:
        return _empty(kind, note)
    today = db.today()
    found = db.rows("""
        SELECT p.asset_id, a.name AS area, w.team_id, w.well_type, p.maintenance_id AS install_job,
               substr(p.started_at, 1, 10) AS installed_on, p.pump_model, p.pump_serial AS serial,
               p.pump_lot AS lot, p.cost_total_usd AS install_cost_usd, p.cost_parts_usd AS install_parts_usd,
               p.cost_labor_usd AS install_labor_usd, p.report_path, p.is_current,
               s.status_now, s.inspection_id AS latest_inspection_id, rl.replace_by
        FROM pump_installs p
        JOIN wells w ON w.asset_id = p.asset_id
        JOIN areas a ON a.area_id = w.area_id
        JOIN recall_lots rl ON rl.lot = p.pump_lot
        LEFT JOIN well_status_now s ON s.asset_id = p.asset_id
        WHERE p.recalled AND substr(p.started_at, 1, 10) <= :today
          AND COALESCE(w.status, '') <> 'plugged_and_abandoned' AND w.well_type <> 'T500'
          AND (:area_id IS NULL OR w.area_id = :area_id)
        ORDER BY a.name, p.asset_id""", {"today": today, "area_id": area_id})
    current = {r["asset_id"]: r for r in db.rows(
        "SELECT asset_id, maintenance_id, substr(started_at, 1, 10) AS date, pump_lot FROM pump_installs WHERE is_current")}
    wells = sorted({r["asset_id"] for r in found})
    reports, last = _user_reports(wells), _last_repairs(wells, today)

    rows, ids = [], [CITE_RECALL]
    for r in found:
        a = r.pop("asset_id")
        in_ground = bool(r.pop("is_current"))
        if not in_ground and not include_replaced:
            continue
        row = {"asset_id": a, **r, "in_ground": in_ground,
               "status_now": STATUS_LABEL.get(r["status_now"], r["status_now"]),
               "overdue": in_ground and today > (r["replace_by"] or today),
               "last_repair": last.get(a), "user_reports": reports.get(a, [])}
        if not in_ground:
            c = current[a]
            row["replaced_by"] = {"maintenance_id": c["maintenance_id"], "date": c["date"], "new_lot": c["pump_lot"]}
            ids.append(c["maintenance_id"])
        rows.append(row)
        ids += [a, r["install_job"], r["latest_inspection_id"]] + [u["note_id"] for u in row["user_reports"]]
    n_in = sum(r["in_ground"] for r in rows)
    notes = [f"{n_in} recalled pump(s) in the ground on {today}, from the latest 'Parts installed' line "
             f"of each well's repair reports ({CITE_RECALL}). The replacement deadline was 31 Dec 2026."]
    by_area: dict[str, int] = {}
    for r in rows:
        if r["in_ground"]:
            by_area[r["area"]] = by_area.get(r["area"], 0) + 1
    if by_area:
        notes.append("By area: " + "; ".join(f"{k}: {v}" for k, v in sorted(by_area.items())))
    if any(r["user_reports"] for r in rows):
        notes.append("Some wells have user reports (user_reports). They are not work orders: say who "
                     "reported what and when, mark them unconfirmed, and keep the well in the list.")
    return _result(kind, rows, ids, notes)


# ----------------------------------------------------------------------------
# OPS-3 status conflicts
# ----------------------------------------------------------------------------

def status_conflicts(area: str | None = None) -> ToolResult:
    """Wells where the latest inspection and the latest operator note about shutting in or
    restarting the well disagree about whether it is producing oil (Operations SOP OPS-3).

    OPS-3: the MORE RECENT of the two decides. A shut-in note newer than the inspection ->
    not producing (shut in), even if the inspection reads producing. A restart note newer than
    the inspection -> producing (unconfirmed) until an inspection confirms it. An inspection
    newer than the note -> the inspection decides. Readings are after data_correction notes.
    Notes older than the latest inspection count only if written within 30 days before it
    (an older shut-in note is just history: the well was restarted since).
    One row per well: asset_id, area, inspection (id, date, what it shows), note (id, time,
    text, says), newer, status_now, why.
    """
    kind = "status_conflicts"
    area_id, note = _area(area)
    if note:
        return _empty(kind, note)
    found = db.rows("""
        SELECT s.asset_id, s.area_name AS area, s.well_type, s.inspection_id, s.inspected_at, s.method,
               s.is_producing, s.temp_delta_c, s.producing_threshold_c, s.correction_ids,
               s.status_note_id, s.status_note_at, s.status_note_event, s.status_note_text,
               s.status_now, s.well_status
        FROM well_status_now s
        WHERE s.status_note_id IS NOT NULL
          AND ((s.status_note_event = 'shut_in' AND s.is_producing) OR
               (s.status_note_event = 'restart' AND NOT s.is_producing))
          AND (s.status_note_at > s.inspected_at
               OR julianday(s.inspected_at) - julianday(s.status_note_at) <= :recent_days)
          AND (:area_id IS NULL OR s.area_id = :area_id)
        ORDER BY s.area_name, s.asset_id""", {"area_id": area_id, "recent_days": RECENT_NOTE_DAYS})
    rows, ids = [], [CITE_OPS3]
    for r in found:
        shows = "producing" if r["is_producing"] else "not producing"
        note_newer = r["status_note_at"] > r["inspected_at"]
        says = "shut in" if r["status_note_event"] == "shut_in" else "restarted"
        if r["well_status"] == "plugged_and_abandoned":
            why = "The well is plugged and abandoned (metadata)."
        elif note_newer:
            why = (f"The {says} note ({r['status_note_at'][:16].replace('T', ' ')}) is newer than the "
                   f"inspection ({r['inspected_at'][:16].replace('T', ' ')}), so it decides (OPS-3)."
                   + (" Unconfirmed until an inspection shows the well producing."
                      if r["status_note_event"] == "restart" else ""))
        else:
            why = (f"The inspection ({r['inspected_at'][:16].replace('T', ' ')}) is newer than the {says} "
                   f"note ({r['status_note_at'][:16].replace('T', ' ')}), so the inspection decides (OPS-3).")
        rows.append({
            "asset_id": r["asset_id"], "area": r["area"], "well_type": r["well_type"],
            "inspection_id": r["inspection_id"], "inspected_at": r["inspected_at"], "method": r["method"],
            "inspection_shows": f"{shows} ({r['temp_delta_c']:.1f} °C above air; producing needs "
                                f">= {r['producing_threshold_c']:g} °C)",
            "correction_ids": r["correction_ids"],
            "note_id": r["status_note_id"], "note_at": r["status_note_at"], "note_text": r["status_note_text"],
            "note_says": says, "newer": "operator note" if note_newer else "inspection",
            "status_now": STATUS_LABEL.get(r["status_now"], r["status_now"]), "why": why})
        ids += [r["asset_id"], r["inspection_id"], r["status_note_id"]] + (r["correction_ids"] or "").split()
    notes = [f"{len(rows)} well(s) where the latest inspection and the latest shut-in/restart operator "
             f"note disagree ({CITE_OPS3}); notes older than the inspection count if within "
             f"{RECENT_NOTE_DAYS} days of it."]
    return _result(kind, rows, ids, notes)


# ----------------------------------------------------------------------------
# Operator concerns (Q7)
# ----------------------------------------------------------------------------

def _t500_falling(asset_id: str) -> str | None:
    """T500 manual §5: wellhead-to-air difference lower three inspections in a row (four
    readings), falling 3 °C or more in total, while producing. Checked on the latest readings."""
    r = db.rows("""SELECT inspection_id, inspected_date, temp_delta_c, is_producing FROM inspections_effective
                   WHERE asset_id = ? ORDER BY inspected_at DESC LIMIT 4""", (asset_id,))
    if len(r) < 4:
        return None
    r = r[::-1]
    d = [x["temp_delta_c"] for x in r]
    if all(d[i + 1] < d[i] for i in range(3)) and d[0] - d[3] >= 3 and all(x["is_producing"] for x in r):
        return (f"T500 falling wellhead-to-air difference: {d[0]:.1f} → {d[3]:.1f} °C over "
                f"{r[0]['inspection_id']}..{r[3]['inspection_id']} ({r[0]['inspected_date']} to "
                f"{r[3]['inspected_date']}); manual says schedule an ESP drive and insulation check ({CITE_T500})")
    return None


def operator_concerns(start: str | None = None, end: str | None = None, area: str | None = None,
                      top_n: int = 10) -> ToolResult:
    """Wells whose operators wrote notes that the well sounds or behaves wrong (rod squeal,
    rattle, fluid pound, tagging bottom, amps hunting, drive tripping, leak) between start and end
    (default: the last month, today minus 1 month through today), and that have had NO repair
    since the latest such note. Ranked by how likely the well needs a repair in the next 90 days.

    score = sum of note weights (drive tripping/leak 3, amps hunting 2.5, fluid pound/tagging
    bottom 2, rattle 1.5, rod squeal 1) + 3 if a T500 well shows the falling-temperature warning
    (T500 manual §5) + 2 if a recalled pump is in the ground + 0.5 per corrective repair in the last
    12 months (max 2) + 1 if the latest inspection reads not producing. The weights are a judgement.
    Columns: rank, asset_id, area, well_type, score, note_evidence [{note_id, date, quote}],
    other_signs [text with IDs], last_repair {maintenance_id, date, equipment_kind, issue}.
    """
    kind = "operator_concerns"
    today = db.today()
    start = start or _months_before(today, 1)
    end = end or today
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    area_id, note = _area(area)
    if note:
        return _empty(kind, note)
    found = db.rows("""
        SELECT n.asset_id, n.note_id, n.created_at, n.text, n.symptom, a.name AS area, w.well_type
        FROM notes n JOIN wells w ON w.asset_id = n.asset_id JOIN areas a ON a.area_id = w.area_id
        WHERE n.source = 'dataset' AND n.symptom IS NOT NULL
          AND substr(n.created_at, 1, 10) BETWEEN :start AND :end
          AND COALESCE(w.status, '') <> 'plugged_and_abandoned'
          AND (:area_id IS NULL OR w.area_id = :area_id)
        ORDER BY n.asset_id, n.created_at""", {"start": start, "end": end, "area_id": area_id})
    by_well: dict[str, list[dict]] = {}
    for n in found:
        by_well.setdefault(n["asset_id"], []).append(n)
    wells = sorted(by_well)
    last = _last_repairs(wells, today)
    year_ago = _months_before(today, 12)
    recalled = {r["asset_id"] for r in db.rows("SELECT asset_id FROM pump_installs WHERE is_current AND recalled")}
    status = {r["asset_id"]: r for r in db.rows(
        "SELECT asset_id, inspection_id, is_producing, temp_delta_c FROM well_status_now "
        "WHERE asset_id IN (SELECT value FROM json_each(?))", (json.dumps(wells),))}
    corrective = {r["asset_id"]: r for r in db.rows("""
        SELECT asset_id, COUNT(*) AS n, group_concat(maintenance_id, ' ') AS ids FROM maintenance
        WHERE maintenance_type = 'corrective' AND substr(started_at, 1, 10) BETWEEN ? AND ?
          AND asset_id IN (SELECT value FROM json_each(?)) GROUP BY asset_id""",
        (year_ago, today, json.dumps(wells)))}

    ranked, skipped = [], []
    for a, ns in by_well.items():
        latest_note = ns[-1]["created_at"]
        lr = last.get(a)
        if lr and lr["date"] >= latest_note[:10]:
            skipped.append(a)
            continue
        score = sum(SYMPTOM_WEIGHT.get(n["symptom"], 1.0) for n in ns)
        signs = []
        if ns[0]["well_type"] == "T500" and (w := _t500_falling(a)):
            score += 3
            signs.append(w)
        if a in recalled:
            score += 2
            signs.append("recalled pump still in the ground (supplier recall notice)")
        if c := corrective.get(a):
            score += min(2.0, 0.5 * c["n"])
            signs.append(f"{c['n']} corrective repair(s) in the last 12 months: {c['ids']}")
        s = status.get(a)
        if s and not s["is_producing"]:
            score += 1
            signs.append(f"latest inspection {s['inspection_id']} reads not producing "
                         f"({s['temp_delta_c']:.1f} °C above air)")
        ranked.append({
            "asset_id": a, "area": ns[0]["area"], "well_type": ns[0]["well_type"], "score": round(score, 1),
            "note_evidence": [{"note_id": n["note_id"], "date": n["created_at"][:16].replace("T", " "),
                               "quote": n["text"]} for n in ns],
            "other_signs": signs, "last_repair": lr})
    ranked.sort(key=lambda r: (-r["score"], r["asset_id"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    rows = [{"rank": r.pop("rank"), **r} for r in ranked[:top_n]]
    ids = []
    for r in rows:
        ids += [r["asset_id"]] + [n["note_id"] for n in r["note_evidence"]]
        if r["last_repair"]:
            ids.append(r["last_repair"]["maintenance_id"])
    notes = [f"Notes from {start} to {end}: {len(by_well)} well(s) with symptom notes; {len(skipped)} had a "
             f"repair after the latest note and are left out; {len(ranked)} ranked, top {len(rows)} shown.",
             "The score weights are a judgement (see the tool description); say so."]
    return _result(kind, rows, ids, notes)


# ----------------------------------------------------------------------------
# Field temperature (Q11)
# ----------------------------------------------------------------------------

def field_temperature(start: str, end: str, group_by: str = "area") -> ToolResult:
    """Wellhead temperature across the field by month, from producing readings, to see which
    part of the field runs hotter and whether that holds month after month.

    group_by: 'area' (default) or 'region' (the compass part of the area name: Northeast,
    Northwest, Southeast, Southwest). Rows (heatmap-friendly): group, month, mean_wellhead_c,
    mean_ambient_c, mean_delta_c, readings, t500_share (ESP wells run hotter by design).
    The notes rank the groups overall, count the months each group was hottest, and repeat the
    comparison within each well type, so the answer can say whether the well-type mix explains it.
    """
    kind = "field_temperature"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    if group_by not in ("area", "region"):
        return _empty(kind, "group_by must be 'area' or 'region'")
    grp = "a.name" if group_by == "area" else "substr(a.name, 1, instr(a.name, ' ') - 1)"
    found = db.rows(f"""
        SELECT {grp} AS grp, substr(e.inspected_date, 1, 7) AS month, e.well_type,
               e.wellhead_temp_c, e.ambient_temp_c, e.temp_delta_c
        FROM inspections_effective e JOIN areas a ON a.area_id = e.area_id
        WHERE e.is_producing AND e.inspected_date BETWEEN :s AND :e""", {"s": start, "e": end})
    cells: dict[tuple, list] = {}
    for r in found:
        cells.setdefault((r["grp"], r["month"]), []).append(r)
    rows = []
    for (g, m), rs in sorted(cells.items()):
        rows.append({"group": g, "month": m, "mean_wellhead_c": round(mean(x["wellhead_temp_c"] for x in rs), 1),
                     "mean_ambient_c": round(mean(x["ambient_temp_c"] for x in rs), 1),
                     "mean_delta_c": round(mean(x["temp_delta_c"] for x in rs), 1), "readings": len(rs),
                     "t500_share": round(sum(x["well_type"] == "T500" for x in rs) / len(rs), 2)})

    def ranking(rs, key="wellhead_temp_c"):
        by: dict[str, list] = {}
        for x in rs:
            by.setdefault(x["grp"], []).append(x[key])
        return sorted(((g, round(mean(v), 1)) for g, v in by.items()), key=lambda t: -t[1])

    notes = ["Overall mean wellhead °C (producing readings): "
             + "; ".join(f"{g} {v}" for g, v in ranking(found)),
             "Overall mean °C above air: " + "; ".join(f"{g} {v}" for g, v in ranking(found, "temp_delta_c"))]
    months = sorted({m for _, m in cells})
    hottest: dict[str, int] = {}
    for m in months:
        ms = [r for r in rows if r["month"] == m]
        top = max(ms, key=lambda r: r["mean_wellhead_c"])["group"]
        hottest[top] = hottest.get(top, 0) + 1
    notes.append(f"Hottest group per month ({len(months)} months): "
                 + "; ".join(f"{g} {n}" for g, n in sorted(hottest.items(), key=lambda t: -t[1])))
    for wt in sorted({r["well_type"] for r in found}):
        notes.append(f"Within {wt} only, mean wellhead °C: "
                     + "; ".join(f"{g} {v}" for g, v in ranking([r for r in found if r["well_type"] == wt])))
    notes.append("Compare within well type before blaming geography: T500 (ESP) wells run hotter by design "
                 "(T500 manual §3), so an area with many T500 wells looks hotter overall.")
    return _result(kind, rows, [], notes)


# ----------------------------------------------------------------------------
# What the data measures (Q1, Q2)
# ----------------------------------------------------------------------------

def data_coverage(topic: str) -> ToolResult:
    """What the data measures, to check before answering a question about a quantity that may
    not be recorded (e.g. 'pressure', 'oil volume', 'production'). Returns the measured fields
    (table, field, unit, date range, rows) and how often the topic word appears in reports,
    operator notes and documents, with examples. If a quantity is not measured, say so plainly
    and offer the closest proxy, labelled as a proxy.
    """
    kind = "data_coverage"
    ins = db.rows("SELECT MIN(inspected_date) AS a, MAX(inspected_date) AS b, COUNT(*) AS n FROM inspections")[0]
    mnt = db.rows("SELECT MIN(substr(started_at,1,10)) AS a, MAX(substr(started_at,1,10)) AS b, COUNT(*) AS n "
                  "FROM maintenance")[0]
    rng_i, rng_m = f"{ins['a']} to {ins['b']}", f"{mnt['a']} to {mnt['b']}"
    rows = [
        {"table": "inspections", "field": "wellhead_temp_c", "unit": "°C", "dates": rng_i, "rows": ins["n"],
         "what": "wellhead temperature, weekly drone/manual inspection"},
        {"table": "inspections", "field": "ambient_temp_c", "unit": "°C", "dates": rng_i, "rows": ins["n"],
         "what": "air temperature at the inspection"},
        {"table": "inspections", "field": "producing (derived)", "unit": "yes/no", "dates": rng_i, "rows": ins["n"],
         "what": "wellhead minus air >= the well type's threshold; no rate or volume"},
        {"table": "inspections", "field": "spill_detected, spill_area_pct, spill_est_volume_bbl", "unit": "bbl, %",
         "dates": rng_i, "rows": ins["n"], "what": "spills seen by the inspection (AI estimate from images)"},
        {"table": "maintenance", "field": "downtime_hours, cost_usd", "unit": "h, USD", "dates": rng_m,
         "rows": mnt["n"], "what": "repair jobs: length and cost"},
        {"table": "wells", "field": "lat, lon, well_type, area, team", "unit": "", "dates": "", "rows": None,
         "what": "well location and attributes"},
    ]
    word = topic.strip().lower()
    stem = word.split()[0] if word else ""
    hits = []
    if stem:
        like = f"%{stem}%"
        for label, sql in [
            ("repair reports", "SELECT maintenance_id AS id, body_md AS t FROM maintenance_reports WHERE lower(body_md) LIKE ?"),
            ("operator notes", "SELECT note_id AS id, text AS t FROM notes WHERE lower(text) LIKE ?"),
            ("inspection remarks", "SELECT inspection_id AS id, notes AS t FROM inspections WHERE lower(notes) LIKE ?"),
            ("documents", "SELECT doc_id || ' §' || heading AS id, body AS t FROM doc_sections WHERE lower(body) LIKE ?"),
        ]:
            found = db.rows(sql, (like,))
            ex = []
            for f in found[:3]:
                t = f["t"] or ""
                i = t.lower().find(stem)
                ex.append({"id": f["id"], "text": t[max(0, i - 80): i + 120].replace("\n", " ")})
            hits.append({"table": label, "field": f"mentions of '{stem}'", "unit": "", "dates": "",
                         "rows": len(found), "what": ex})
    rows += hits
    notes = ["Measured quantities: wellhead and air temperature, spill area and volume, repair length and cost. "
             "There is NO reservoir or well pressure series and NO oil production volume or rate."]
    if stem in ("pressure", "pressures", "reservoir"):
        notes.append("Pressure appears only as flowline pressure-test values in repair reports (psi, at the "
                     "repair) and separator high-pressure alarms in notes; these are not reservoir pressure. "
                     "A reservoir pressure map cannot be made from this data; say so. A proxy that IS in the "
                     "data (e.g. well locations, wellhead temperature by area) must be labelled as not pressure.")
    if stem in ("oil", "production", "produced", "volume", "barrels", "bbl", "rate"):
        notes.append("Oil volumes are not recorded (bbl appears only for spills). The closest proxy is how "
                     "long each well was producing: producing_days ranks wells by producing inspections x 7 days.")
    return _result(kind, rows, [], notes)


def producing_days(start: str, end: str, area: str | None = None, top_n: int = 10) -> ToolResult:
    """PROXY for "which well produced the most": wells ranked by days producing in the period
    (weekly inspections that read producing x 7 days), then by mean °C above air. The data has no
    oil volumes, so this ranks uptime, not barrels; say so in the answer.
    Columns: rank, asset_id, area, well_type, producing_days, inspections, producing_inspections,
    mean_delta_c.
    """
    kind = "producing_days"
    if note := _date_note(start=start, end=end):
        return _empty(kind, note)
    area_id, note = _area(area)
    if note:
        return _empty(kind, note)
    found = db.rows("""
        SELECT e.asset_id, a.name AS area, w.well_type, COUNT(*) AS inspections,
               SUM(e.is_producing) AS producing_inspections, SUM(e.is_producing) * 7 AS producing_days,
               ROUND(AVG(CASE WHEN e.is_producing THEN e.temp_delta_c END), 1) AS mean_delta_c
        FROM inspections_effective e JOIN wells w ON w.asset_id = e.asset_id JOIN areas a ON a.area_id = w.area_id
        WHERE e.inspected_date BETWEEN :s AND :e AND (:area_id IS NULL OR w.area_id = :area_id)
        GROUP BY e.asset_id ORDER BY producing_days DESC, mean_delta_c DESC, e.asset_id""",
        {"s": start, "e": end, "area_id": area_id})
    top = found[0]["producing_days"] if found else 0
    tied = sum(r["producing_days"] == top for r in found)
    rows = [{"rank": i, **r} for i, r in enumerate(found[:top_n], 1)]
    notes = ["PROXY: the data has no oil volumes or rates; this ranks days producing (weekly inspections x 7).",
             f"{tied} well(s) tie on the most producing days ({top}); they are ordered by mean °C above air, "
             "which is not a measure of oil volume either."]
    return _result(kind, rows, [r["asset_id"] for r in rows], notes)


ASSET_TOOLS = [recalled_pumps, status_conflicts, operator_concerns, field_temperature, data_coverage, producing_days]
