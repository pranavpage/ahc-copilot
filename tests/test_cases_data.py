"""Checks evals/cases.yaml: its structure, and every expected value against data/copilot.db.

Each case has a FACTS function that answers the question with SQL and returns the strings an answer
must contain (IDs, numbers, ISO dates, names). Every `must_include` entry must be one of them.
Values that a user gives in the chat (not in the data) come from `said()`, which checks that the
value is in the case's messages.
"""

import re
from datetime import date, timedelta

import pytest

from copilot import db
from evals.cases import EvalCase, load_cases

CASES = load_cases()
BY_ID = {c.id: c for c in CASES}
TODAY = db.today()

ID_TABLES = {
    "WELL": ("wells", "asset_id"),
    "INS": ("inspections", "inspection_id"),
    "MNT": ("maintenance", "maintenance_id"),
    "REG": ("regulatory_events", "event_id"),
    "CTX": ("notes", "note_id"),
}
ID_RE = re.compile(r"^(WELL|INS|MNT|REG|CTX)-\d{4}(-\d{3,4})?$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def q(sql: str, *params) -> list[dict]:
    return db.rows(sql, params)


def n(x: float) -> str:
    """A number as the expected answers write it: one decimal, no '.0' on whole numbers."""
    r = round(x, 1)
    return str(int(r)) if r == int(r) else str(r)


def n1(x: float) -> str:
    """A number with exactly one decimal ('24.0')."""
    return f"{x:.1f}"


def name(user_id: str) -> str:
    return q("SELECT name FROM users WHERE user_id = ?", user_id)[0]["name"]


def rule(key: str, well_type: str | None = None) -> dict:
    """The active document rule for a key (for one well type, or the fleet-wide one)."""
    return q("SELECT value, protocol_id FROM rules WHERE rule_key = ? AND status = 'active' "
             "AND well_type IS ?", key, well_type)[0]


def plus_days(iso: str, days: float) -> str:
    return (date.fromisoformat(iso[:10]) + timedelta(days=days)).isoformat()


def date_alts(iso: str) -> list[str]:
    """The alternatives a date is written as in cases.yaml."""
    d = date.fromisoformat(iso)
    return [iso, f"{d.day} {d:%b}".lower(), f"{d:%b} {d.day}".lower(), f"{d:%B} {d.day}".lower()]


def chain(case_id: str) -> list[EvalCase]:
    """The case and every case it follows, recursively."""
    case = BY_ID[case_id]
    return [c for f in case.follows for c in chain(f)] + [case]


def said(case_id: str, *values: str) -> set[str]:
    """Values a user gives in the chat. They must appear in the messages of the case or its chain."""
    text = " ".join(t.message for c in chain(case_id) for t in c.turns or [])
    missing = [v for v in values if v not in text]
    assert not missing, f"{case_id}: not said in the chat: {missing}"
    return set(values)


def groups(case: EvalCase) -> list[list[str]]:
    return [g if isinstance(g, list) else [g] for g in case.must_include]


# ---------------------------------------------------------------------------
# Facts: each function answers its case from the database
# ---------------------------------------------------------------------------

FACTS = {}


def facts(case_id):
    def register(fn):
        FACTS[case_id] = fn
        return fn
    return register


@facts("Q1")
def q1():
    s = q("SELECT * FROM well_status_now WHERE asset_id = 'WELL-0001'")[0]
    assert not s["is_producing"] and s["recorded_status"] == "active"
    out = {s["inspection_id"], s["inspected_at"][:10], name(s["inspector_user_id"]), n(s["temp_delta_c"])}
    for note in q("SELECT * FROM notes WHERE asset_id = 'WELL-0001' AND valid_from <= ? AND valid_to >= ?",
                  TODAY, TODAY):
        out |= {note["note_id"], name(note["author_user_id"]), note["valid_to"]}
    return out


def not_producing_now(area: str) -> list[dict]:
    return q("SELECT * FROM well_status_now WHERE area_name = ? AND NOT is_producing", area)


def open_repairs(asset_ids: list[str]) -> set[str]:
    marks = ",".join("?" * len(asset_ids))
    return {r["maintenance_id"] for r in q(
        f"SELECT maintenance_id FROM maintenance WHERE asset_id IN ({marks}) "
        "AND substr(started_at, 1, 10) <= ? AND completed_at > ?", *asset_ids, TODAY, TODAY)}


@facts("Q2")
def q2():
    rows = not_producing_now("Northeast Block 8")
    wells = [r["asset_id"] for r in rows]
    return ({*wells} | {r["inspected_at"][:10] for r in rows} | {n(r["temp_delta_c"]) for r in rows}
            | open_repairs(wells))


@facts("Q3")
def q3():
    rows = q("SELECT inspected_date, is_producing FROM inspections_effective WHERE asset_id = 'WELL-0001' "
             "AND inspected_date > ? AND inspected_date <= ? ORDER BY inspected_date",
             plus_days(TODAY, -7 * 13), TODAY)
    return ({str(len(rows)), rows[0]["inspected_date"]}
            | {r["inspected_date"] for r in rows if not r["is_producing"]})


@facts("Q4")
def q4():
    start = plus_days(TODAY, -4 * 365)
    rows = q("SELECT spill_volume_bbl FROM spills WHERE asset_id = 'WELL-0001' AND inspected_date > ?", start)
    corrected = q("SELECT c.target_id, c.note_id FROM corrections c JOIN inspections i "
                  "ON i.inspection_id = c.target_id WHERE c.asset_id = 'WELL-0001' "
                  "AND c.field = 'spill_detected' AND c.corrected_value = 0 AND c.status = 'active' "
                  "AND substr(i.inspected_at, 1, 10) > ?", start)
    return ({n(sum(r["spill_volume_bbl"] for r in rows))} | {n(r["spill_volume_bbl"]) for r in rows}
            | {c["target_id"] for c in corrected} | {c["note_id"] for c in corrected})


@facts("Q5")
def q5():
    rows = q("SELECT * FROM inspections_effective WHERE asset_id = 'WELL-0001' "
             "AND inspected_date LIKE '2025-%' AND NOT is_producing")
    repairs = q("SELECT maintenance_id FROM maintenance WHERE triggered_by_inspection_id IN "
                f"({','.join('?' * len(rows))})", *[r["inspection_id"] for r in rows])
    out = {n(sum(r["downtime_days"] for r in rows))} | {m["maintenance_id"] for m in repairs}
    for r in rows:
        out |= {r["inspected_date"], n(r["wellhead_temp_c"]), n(r["ambient_temp_c"]), n(r["temp_delta_c"])}
    return out


def top_downtime(area: str, months: int, top: int) -> list[dict]:
    return q("SELECT e.asset_id, SUM(e.downtime_days) AS days FROM inspections_effective e "
             "JOIN areas a ON a.area_id = e.area_id WHERE a.name = ? "
             "AND e.inspected_date >= date(?, ?) AND e.inspected_date <= ? "
             "GROUP BY e.asset_id ORDER BY days DESC, e.asset_id LIMIT ?",
             area, TODAY, f"-{months} months", TODAY, top)


@facts("Q6")
def q6():
    rows = top_downtime("Northeast Block 7", 4, 3)
    return {r["asset_id"] for r in rows} | {n(r["days"]) for r in rows}


def area_spills(area: str, start: str, end: str = TODAY) -> list[dict]:
    return q("SELECT s.* FROM spills s JOIN areas a ON a.area_id = s.area_id "
             "WHERE a.name = ? AND s.inspected_date >= ? AND s.inspected_date <= ?", area, start, end)


@facts("Q7")
def q7():
    rows = area_spills("Northeast Block 8", plus_days(TODAY, -90))
    return {r["asset_id"] for r in rows} | {n(r["spill_volume_bbl"]) for r in rows}


@facts("Q8")
def q8():
    rows = q("SELECT a.name, COUNT(*) AS spills FROM spills s JOIN areas a ON a.area_id = s.area_id "
             "WHERE s.inspected_date LIKE '2026-%' GROUP BY a.name")
    return {r["name"] for r in rows} | {str(r["spills"]) for r in rows}


@facts("Q9")
def q9():
    events = q("SELECT * FROM regulatory_events WHERE asset_id = 'WELL-0001' AND date > ?",
               plus_days(TODAY, -365))
    out = {e["event_id"] for e in events} | {e["protocol_id"] for e in events}
    out |= {n(e["hours_to_report"]) for e in events if e["hours_to_report"]}
    out.add(n(sum(e["fine_usd"] for e in events if e["status"] == "open")))
    # Every event comes from one spill.
    (inspection,) = {e["related_inspection_id"] for e in events}
    spill = q("SELECT * FROM spills WHERE inspection_id = ?", inspection)[0]
    out |= {spill["inspected_date"], n(spill["spill_volume_bbl"])}
    # SR-02: containment time, found only in the repair report.
    sr02 = rule("containment_max_hours")
    assert spill["containment_hours"] > sr02["value"]
    out.add(sr02["protocol_id"])
    # SR-03: cleanup verification deadline.
    out.add(plus_days(spill["inspected_date"], rule("cleanup_verification_days")["value"]))
    # RC-04: the notice of violation needs a response, and none is recorded.
    rc04 = rule("nov_response_days")
    (nov,) = [e for e in events if e["event_type"] == "notice_of_violation"]
    assert not [e for e in events if e["event_type"] == "nov_response_filed"]
    out |= {rc04["protocol_id"], plus_days(nov["date"], rc04["value"])}
    return out


@facts("Q10")
def q10():
    limit = rule("containment_max_hours")["value"]
    rows = [r for r in area_spills("Southwest Block 24", plus_days(TODAY, -90))
            if r["containment_hours"] and r["containment_hours"] > limit]
    return {v for r in rows for v in (r["asset_id"], r["inspection_id"], r["maintenance_id"],
                                      n(r["containment_hours"]))}


@facts("Q11")
def q11():
    wells = [r["asset_id"] for r in top_downtime("Northeast Block 7", 4, 3)]
    rows = q("SELECT asset_id, SUM(cost_total_usd) AS cost FROM maintenance "
             f"WHERE asset_id IN ({','.join('?' * len(wells))}) "
             "AND started_at >= ? AND substr(started_at, 1, 10) <= ? GROUP BY asset_id",
             *wells, TODAY[:4] + "-01-01", TODAY)
    return set(wells) | {n(r["cost"]) for r in rows}


def corrected_reading(case_id: str) -> tuple[dict, float]:
    """WELL-0164's latest inspection and the wellhead temperature the user gives in Q12a."""
    (wellhead,) = said(case_id, "41.0")
    s = q("SELECT * FROM well_status_now WHERE asset_id = 'WELL-0164'")[0]
    return s, float(wellhead)


@facts("Q12a")
def q12a():
    s, wellhead = corrected_reading("Q12a")
    delta = wellhead - s["ambient_temp_c"]
    assert not s["is_producing"] and delta >= s["producing_threshold_c"]
    return {s["inspection_id"], n1(s["wellhead_temp_c"]), n1(wellhead), n1(s["ambient_temp_c"]), n1(delta),
            name(s["inspector_user_id"])}


@facts("Q12b")
def q12b():
    s, wellhead = corrected_reading("Q12b")
    wells = [r["asset_id"] for r in not_producing_now("Northeast Block 8")
             if r["asset_id"] != s["asset_id"] or wellhead - s["ambient_temp_c"] < s["producing_threshold_c"]]
    return set(wells) | open_repairs(wells)


@facts("Q13")
def q13():
    (volume,) = said("Q13", "5.4")
    (spill,) = q("SELECT * FROM spills WHERE asset_id = 'WELL-0151' AND inspected_date = '2026-09-24'")
    assert float(volume) >= rule("spill_reportable_min_bbl")["value"] > spill["spill_volume_bbl"]
    assert not q("SELECT 1 FROM regulatory_events WHERE related_inspection_id = ?", spill["inspection_id"])
    sr03 = rule("cleanup_verification_days")
    return {spill["inspection_id"], spill["maintenance_id"], volume, n(spill["raw_spill_est_volume_bbl"]),
            n(spill["containment_hours"]), rule("spill_notice_hours")["protocol_id"],
            rule("containment_max_hours")["protocol_id"], sr03["protocol_id"],
            plus_days(spill["inspected_at"], sr03["value"])}


def rca_wells(area: str, min_repairs: dict[str, float] | None = None) -> set[str]:
    """Wells that need a pump jack root-cause analysis. min_repairs overrides the manual per type."""
    rows = q("SELECT w.asset_id, w.well_type, COUNT(*) AS repairs, r.value AS needed FROM maintenance m "
             "JOIN wells w ON w.asset_id = m.asset_id JOIN areas a ON a.area_id = w.area_id "
             "JOIN well_rules r ON r.asset_id = w.asset_id AND r.rule_key = 'rca_corrective_count' "
             "JOIN well_rules win ON win.asset_id = w.asset_id AND win.rule_key = 'rca_window_months' "
             "WHERE a.name = ? AND m.maintenance_type = 'corrective' AND m.equipment_kind = 'pump_jack' "
             "AND substr(m.started_at, 1, 10) > date(?, '-' || CAST(win.value AS INTEGER) || ' months') "
             "AND substr(m.started_at, 1, 10) <= ? GROUP BY w.asset_id", area, TODAY, TODAY)
    min_repairs = min_repairs or {}
    return {r["asset_id"] for r in rows if r["repairs"] >= min_repairs.get(r["well_type"], r["needed"])}


@facts("Q14a")
def q14a():
    return rca_wells("Northeast Block 7")


@facts("Q14b")
def q14b():
    said("Q14b", "all T350 wells", "after 2 repairs")
    return rca_wells("Northeast Block 7", {"T350": 2}) | {name(BY_ID["Q14b"].turns[0].user_id)}


@facts("Q15a")
def q15a():
    s, wellhead = corrected_reading("Q15a")
    return {s["inspection_id"], n1(wellhead), name(BY_ID["Q12a"].turns[0].user_id)}


@facts("Q15b")
def q15b():
    (volume,) = said("Q15b", "5.4")
    corrected = {"INS-0151-0201": float(volume)}
    reportable = rule("spill_reportable_min_bbl")["value"]
    rows = [r for r in area_spills("Northeast Block 8", plus_days(TODAY, -90))
            if corrected.get(r["inspection_id"], r["spill_volume_bbl"]) >= reportable]
    return {r["asset_id"] for r in rows} | {volume}


@facts("Q16a")
def q16a():
    said("Q16a", "17 Oct", "10-day")
    return {name(BY_ID["Q16a"].turns[0].user_id), TODAY[:4] + "-10-17", "10"}


@facts("Q17a")
def q17a():
    s = q("SELECT * FROM well_status_now WHERE asset_id = 'WELL-0175'")[0]
    assert not s["is_producing"]
    return {s["inspected_at"][:10], name(s["inspector_user_id"]), n(s["temp_delta_c"]),
            name(BY_ID["Q17a"].turns[0].user_id)}


@facts("Q17b")
def q17b():
    out = q1()
    s = q("SELECT is_producing FROM well_status_now WHERE asset_id = 'WELL-0001'")[0]
    assert not s["is_producing"]
    return out


@facts("Q18")
def q18():
    (spill,) = q("SELECT * FROM spills WHERE asset_id = 'WELL-0101' AND inspected_date LIKE '%-08-20'")
    notes = q("SELECT note_id, author_user_id FROM notes WHERE text LIKE ?", f"%{spill['inspection_id']}%")
    assert not q("SELECT 1 FROM corrections WHERE target_id = ?", spill["inspection_id"])
    return ({spill["inspection_id"], n1(spill["spill_volume_bbl"]), spill["maintenance_id"]}
            | {x["note_id"] for x in notes} | {name(x["author_user_id"]) for x in notes})


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_cases_load():
    assert len(CASES) >= 18


def test_ids_unique():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_all_questions_covered():
    numbers = {int(re.match(r"Q(\d+)", c.id).group(1)) for c in CASES}
    assert numbers == set(range(1, 19))


def test_follows_points_to_earlier_case():
    seen = set()
    for c in CASES:
        assert set(c.follows) <= seen, f"{c.id} follows a case that is not earlier: {c.follows}"
        seen.add(c.id)


def test_single_and_multi_turn():
    for c in CASES:
        number = int(re.match(r"Q(\d+)", c.id).group(1))
        if number <= 10:
            assert c.question and c.visual, c.id
        else:
            assert c.turns, c.id


def test_users_exist():
    users = {r["user_id"] for r in q("SELECT user_id FROM users")}
    for c in CASES:
        assert {c.user_id, *(t.user_id for t in c.turns or [])} <= users, c.id


def test_a_new_user_starts_a_new_chat():
    for c in CASES:
        for prev, turn in zip(c.turns or [], (c.turns or [])[1:]):
            assert turn.user_id == prev.user_id or turn.new_thread, c.id


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_alternatives_are_dates(case):
    for g in groups(case):
        if len(g) > 1:
            assert g == date_alts(g[0]), f"{case.id}: {g}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_record_ids_exist(case):
    for value in [v for g in groups(case) for v in g] + case.must_not_include:
        if m := ID_RE.match(value):
            table, column = ID_TABLES[m.group(1)]
            assert q(f"SELECT 1 FROM {table} WHERE {column} = ?", value), f"{case.id}: {value} not in {table}"


@pytest.mark.parametrize("case", [c for c in CASES if c.must_include], ids=lambda c: c.id)
def test_must_include_comes_from_data(case):
    expected = FACTS[case.id]()
    missing = [g for g in groups(case) if not set(g) & expected]
    assert not missing, f"{case.id}: not backed by the data: {missing}; the data gives {sorted(expected)}"


@pytest.mark.parametrize("case", [c for c in CASES if c.must_include], ids=lambda c: c.id)
def test_well_list_is_complete(case):
    """The wells in must_include are exactly the wells the data gives."""
    wells = {v for g in groups(case) for v in g if v.startswith("WELL-")}
    assert wells == {v for v in FACTS[case.id]() if v.startswith("WELL-")}, case.id


def test_q14b_excludes_a_t200_well_with_two_repairs():
    (well,) = BY_ID["Q14b"].must_not_include
    assert q("SELECT well_type FROM wells WHERE asset_id = ?", well)[0]["well_type"] == "T200"
    assert well not in rca_wells("Northeast Block 7", {"T350": 2})
    assert well in rca_wells("Northeast Block 7", {"T200": 2, "T350": 2})


def test_q16b_excludes_the_wells_from_q11():
    assert set(BY_ID["Q16b"].must_not_include) == {w for w in q11() if w.startswith("WELL-")}
