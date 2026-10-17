"""Asset tools on the TEST data (data/copilot.db, today = 2027-01-15). No LLM or network calls.

Expected values were checked against the raw dataset files ("Parts installed" lines in the
repair reports, context.jsonl operator notes, inspections.jsonl).
"""

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from copilot.config import ROOT, get_settings
from copilot.tools.assets import (data_coverage, field_temperature, operator_concerns, producing_days,
                                  recalled_pumps, status_conflicts)
from copilot.tools.status import well_status

TEST_DB = ROOT / "data" / "copilot.db"


@pytest.fixture(scope="module", autouse=True)
def test_db():
    if not TEST_DB.exists():
        pytest.skip("data/copilot.db not built (uv run python db/load.py)")
    old = os.environ.get("DB_PATH")
    with tempfile.TemporaryDirectory(prefix="copilot-test-data-") as tmp:
        dst = Path(tmp) / "copilot.db"
        with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as a, closing(sqlite3.connect(dst)) as b:
            a.backup(b)
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


def test_recalled_pumps_in_ground():
    r = recalled_pumps()
    wells = {x["asset_id"]: x for x in r.rows}
    assert set(wells) == {"WELL-0031", "WELL-0156", "WELL-0160", "WELL-0263", "WELL-0305", "WELL-0333",
                          "WELL-0426", "WELL-0428", "WELL-0577"}
    assert wells["WELL-0333"]["lot"] == "LOT-2409-A" and wells["WELL-0333"]["install_job"] == "MNT-0333-024"
    assert wells["WELL-0263"]["lot"] == "LOT-2410-B"      # latest install is recalled, an earlier one was not
    assert all(x["overdue"] for x in r.rows)
    nw = recalled_pumps(area="Northwest Block 12")
    assert [x["asset_id"] for x in nw.rows] == ["WELL-0305", "WELL-0333", "WELL-0426", "WELL-0428"]


def test_recalled_pumps_replaced():
    r = recalled_pumps(include_replaced=True)
    replaced = {x["asset_id"]: x for x in r.rows if not x["in_ground"]}
    assert replaced["WELL-0302"]["replaced_by"]["maintenance_id"] == "MNT-0302-031"
    assert "WELL-0302" not in {x["asset_id"] for x in recalled_pumps().rows}


def test_status_conflicts_ops3():
    r = status_conflicts()
    rows = {x["asset_id"]: x for x in r.rows}
    assert len(rows) == 12
    assert rows["WELL-0323"]["status_now"] == "Not producing oil"          # newer shut-in note
    assert rows["WELL-0026"]["status_now"] == "Producing oil (unconfirmed)"  # newer restart note
    assert rows["WELL-0010"]["newer"] == "inspection"                     # T200 -> T350: 17.5 < 20 °C


def test_well_status_status_now():
    r = well_status(asset_ids=["WELL-0323", "WELL-0026", "WELL-0085"])
    s = {x["asset_id"]: x["status_now"] for x in r.rows}
    assert s == {"WELL-0323": "not_producing", "WELL-0026": "producing_unconfirmed", "WELL-0085": "plugged"}


def test_operator_concerns_ranks_unrepaired_wells():
    r = operator_concerns()
    assert len(r.rows) == 10 and r.rows[0]["rank"] == 1
    assert r.rows[0]["asset_id"] == "WELL-0336"
    assert any("T500 falling" in s for s in r.rows[0]["other_signs"])
    for x in r.rows:
        latest = max(n["date"] for n in x["note_evidence"])
        assert not x["last_repair"] or x["last_repair"]["date"] < latest[:10]


def test_field_temperature_within_type():
    r = field_temperature("2026-01-01", "2027-01-15", group_by="region")
    assert r.rows and {x["group"] for x in r.rows} == {"Northeast", "Northwest", "Southeast", "Southwest"}
    assert any(n.startswith("Within T500") for n in r.notes)


def test_data_coverage_and_proxy():
    assert "NO reservoir" in data_coverage("pressure").notes[0]
    r = producing_days("2026-01-01", "2026-12-31", top_n=5)
    assert len(r.rows) == 5 and "PROXY" in r.notes[0]
