"""Compliance tools on the TEST data (data/copilot.db, today = 2027-01-15). No LLM or network calls.

Expected values were checked by hand against the raw dataset files (context.jsonl,
inspections.jsonl, maintenance.jsonl, the MOC memos and the reports).
"""

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from copilot.config import ROOT, get_settings
from copilot.tools.compliance import (
    COMPLIANCE_TOOLS,
    bypasses,
    freeze_checks,
    gas_reports,
    regulator_letter_spills,
    team_summary,
    waiting_reasons,
)

TEST_DB = ROOT / "data" / "copilot.db"


@pytest.fixture(scope="module", autouse=True)
def test_db():
    if not TEST_DB.exists():
        pytest.skip("data/copilot.db not built (uv run python db/load.py)")
    old = os.environ.get("DB_PATH")
    with tempfile.TemporaryDirectory(prefix="copilot-test-data-") as tmp:
        dst = Path(tmp) / "copilot.db"
        with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as a, closing(sqlite3.connect(dst)) as b:
            a.backup(b)   # consistent copy even if the DB is being rebuilt
        os.environ["DB_PATH"] = str(dst)
        get_settings.cache_clear()
        try:
            yield dst
        finally:
            if old is None:
                os.environ.pop("DB_PATH", None)
            else:
                os.environ["DB_PATH"] = old
            get_settings.cache_clear()


def by_id(result):
    return {r["asset_id"]: r for r in result.rows}


def test_tools_list():
    assert len(COMPLIANCE_TOOLS) == 6 and all(callable(t) and t.__doc__ for t in COMPLIANCE_TOOLS)


# --- OPS-1 gas reports -------------------------------------------------------

def test_gas_reports_since_nov():
    r = gas_reports("2026-11-01")
    assert len(r.rows) == 26
    results = [row["result"] for row in r.rows]
    assert results.count("Met") == 17 and results.count("Missed") == 9 and "Pending" not in results
    rows = by_id(r)
    # no maintenance job and only drone inspections after the note
    assert rows["WELL-0332"]["response_id"] == "none" and rows["WELL-0332"]["result"] == "Missed"
    assert rows["WELL-0332"]["reported_at"] == "2026-12-03 12:10 UTC"
    # manual inspection 3.8 h later
    assert rows["WELL-0423"]["response_id"] == "INS-0423-0213"
    assert rows["WELL-0423"]["hours_to_response"] == 3.8 and rows["WELL-0423"]["result"] == "Met"
    # drone inspections on 5 and 12 Nov do not count; the first job is on 14 Nov
    assert rows["WELL-0163"]["response_id"] == "MNT-0163-019" and rows["WELL-0163"]["result"] == "Missed"
    # from 1 Jan 2027 the deadline is 12 h: 16.4 h is late
    assert rows["WELL-0599"]["deadline_hours"] == 12
    assert rows["WELL-0599"]["hours_to_response"] == 16.4 and rows["WELL-0599"]["result"] == "Missed"
    # 31.8 h against 24 h
    assert rows["WELL-0362"]["result"] == "Missed"
    assert rows["WELL-0324"]["deadline_hours"] == 12 and rows["WELL-0324"]["result"] == "Met"
    assert "operations-sop-rev2 §OPS-1 Gas odor response" in r.ids
    assert "CTX-0332-004" in r.ids


def test_gas_reports_area_and_bad_input():
    r = gas_reports("2026-11-01", area="Northwest Block 12")
    assert r.rows and all(row["area"] == "Northwest Block 12" for row in r.rows)
    assert gas_reports("2026-11-01", area="Nowhere").rows == []
    assert gas_reports("1 Nov").rows == []


# --- OPS-2 bypasses ----------------------------------------------------------

def test_bypasses_statuses():
    r = bypasses()
    rows = by_id(r)
    assert {w: row["status"] for w, row in rows.items()} == {
        "WELL-0013": "Allowed",       # MOC-2026-031 extended by MOC-2026-044 to 28 Feb 2027
        "WELL-0062": "Allowed",
        "WELL-0087": "Expired",       # MOC-2026-036 expired 15 Dec, removed 6 Jan
        "WELL-0158": "Expired",       # removed 28 Dec
        "WELL-0248": "Allowed",       # still in, within the extension
        "WELL-0249": "Expired",       # still in today, MOC-2026-036 expired
        "WELL-0284": "Allowed",
        "WELL-0356": "Allowed",
        "WELL-0405": "Not approved",  # no MOC, still in
        "WELL-0461": "Allowed",
        "WELL-0476": "Allowed",
        "WELL-0561": "Not approved",  # no MOC, removed
    }
    assert sorted(w for w, row in rows.items() if row["in_place_now"]) == ["WELL-0248", "WELL-0249", "WELL-0405"]
    assert rows["WELL-0249"]["bypass_out"] == "still in"
    assert rows["WELL-0013"]["approval_valid_until"] == "2027-02-28"
    assert rows["WELL-0087"]["moc_id"] == "MOC-2026-036" and rows["WELL-0087"]["bypass_out"] == "2027-01-06"
    assert rows["WELL-0405"]["moc_id"] is None
    assert {"MOC-2026-031", "MOC-2026-044", "MOC-2026-036", "CTX-0405-003"} <= set(r.ids)


def test_bypasses_area():
    r = bypasses(area="SE-31")
    assert sorted(by_id(r)) == ["WELL-0248", "WELL-0249"]


# --- Regulator letter ----------------------------------------------------------

def test_regulator_letter_spills():
    r = regulator_letter_spills()
    rows = {row["inspection_id"]: row for row in r.rows}
    assert sorted(rows) == ["INS-0119-0209", "INS-0123-0093", "INS-0168-0190",
                            "INS-0182-0208", "INS-0262-0218", "INS-0277-0205"]
    assert {i for i, row in rows.items() if row["compliant"] == "No"} == {
        "INS-0123-0093", "INS-0182-0208", "INS-0262-0218"}
    assert rows["INS-0123-0093"]["cleanup_job"] == "MNT-0123-014"
    assert rows["INS-0168-0190"]["volume_bbl"] == 5.6 and rows["INS-0168-0190"]["compliant"] == "Yes"
    assert all(row["area"] in ("Northeast Block 7", "Northeast Block 8") for row in r.rows)
    # the 4.8 -> 5.6 bbl correction is in Southwest Block 24, outside the letter
    assert all(row["asset_id"] != "WELL-0067" for row in r.rows)
    # 4.7 bbl spill is below the reportable line
    assert "INS-0189-0219" not in rows


def test_regulator_letter_other_area():
    assert regulator_letter_spills(area="Northwest Block 12").rows == []
    assert len(regulator_letter_spills(area="Northeast Block 7").rows) == 3


# --- OPS-5 freeze checks -------------------------------------------------------

def test_freeze_checks_december():
    r = freeze_checks("2026-12-01", "2026-12-31")
    rows = by_id(r)
    assert sorted(w for w, row in rows.items() if row["result"] == "Missed") == [
        "WELL-0310", "WELL-0354", "WELL-0486", "WELL-0531"]
    assert rows["WELL-0421"]["check_job"] == "MNT-0421-032" and rows["WELL-0421"]["result"] == "Met"
    # T500 well producing at 25 °C delta; T500 well at -8.5 °C not producing needs no check
    assert rows["WELL-0445"]["result"] == "Met"
    assert "WELL-0411" not in rows and "WELL-0459" not in rows
    missed = freeze_checks("2026-12-01", "2026-12-31", missed_only=True)
    assert len(missed.rows) == 4


def test_freeze_checks_outside_season():
    assert freeze_checks("2026-06-01", "2026-08-31").rows == []


# --- Waiting reasons -----------------------------------------------------------

def test_waiting_reasons_2026():
    r = waiting_reasons("2026-01-01", "2026-12-31")
    field = {row["reason"]: row for row in r.rows if row["area"] == "All areas"}
    assert set(field) == {"parts", "crews", "contractors", "weather"}
    assert sum(row["jobs"] for row in field.values()) == 632
    assert field["parts"]["jobs"] == 117 and field["weather"]["jobs"] == 139
    # 112 crew + 58 company-rig waits; 130 contractor slots + 76 contractor-rig waits
    assert field["crews"]["jobs"] == 170 and field["contractors"]["jobs"] == 206
    for area in {row["area"] for row in r.rows}:
        assert abs(sum(row["share_pct"] for row in r.rows if row["area"] == area) - 100) < 0.5
    assert any("interim" in n for n in r.notes)


def test_waiting_reasons_rig_separate():
    r = waiting_reasons("2026-01-01", "2026-12-31", rig="separate")
    field = {row["reason"]: row for row in r.rows if row["area"] == "All areas"}
    assert field["workover rig"]["jobs"] == 134 and field["crews"]["jobs"] == 112


# --- Teams ---------------------------------------------------------------------

def test_team_summary_northwest():
    r = team_summary("Northwest Production")
    total = [row for row in r.rows if row["area"] == "All areas"][0]
    assert total["lead"] == "Nathan Pierce" and total["wells_run"] == 150 and total["plugged"] == 0
    assert team_summary("TEAM-NW").rows == r.rows


def test_team_summary_well_team_beats_area():
    se = {row["area"]: row for row in team_summary("Southeast Production").rows}
    assert se["Southwest Block 24"]["wells_run"] == 10 and se["All areas"]["wells_run"] == 210
    ne = {row["area"]: row for row in team_summary("Northeast Production").rows}
    assert ne["All areas"]["wells_run"] == 122 and ne["All areas"]["plugged"] == 2
    assert team_summary("Nowhere").rows == []
