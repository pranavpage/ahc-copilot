"""Feedback tools: corrections, shared notes, user rules (Q12–Q17). Each test restores the DB."""

import pytest
from langchain_core.messages import AIMessage

from copilot import api, db
from copilot.agent import build_tools
from copilot.config import get_settings
from copilot.tools import rca_due, spills, well_records, well_status
from copilot.tools.feedback import add_note, record_correction, set_rule
from evals.runner import db_snapshot
from tests.test_agent_offline import call, use_model  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _restore_db():
    with db_snapshot(get_settings().db_path) as restore:
        yield
        restore()


def as_user(user_id: str) -> dict:
    return {"configurable": {"user_id": user_id, "thread_id": "t-feedback"}}


def rca(asset_id: str) -> list[str]:
    rows = well_records(asset_id, "2025-10-16", "2026-10-16").rows
    return [r["status"] for r in rows if r.get("rule") == "RCA" and "pump_jack" in r["detail"]]


def test_reading_correction_makes_the_well_producing():
    r = record_correction("wellhead_temp_c", 41.0, "thermal gun faulty", asset_id="WELL-0164",
                          date="2026-10-15", config=as_user("U-201"))
    row = r.rows[0]
    assert (row["inspection_id"], row["original_value"], row["corrected_value"]) == ("INS-0164-0205", 24.0, 41.0)
    assert (row["is_producing_before"], row["is_producing"], row["temp_delta_c"]) == (False, True, 21.1)
    assert row["corrected_by"] == "Michael Turner" and row["inspector_name"] == "Tyler Hughes"
    assert any("Pump jack not moving." in n for n in r.notes)
    # The original value stays in the source table.
    assert db.rows("SELECT wellhead_temp_c FROM inspections WHERE inspection_id = 'INS-0164-0205'")[0][
        "wellhead_temp_c"] == 24.0

    # Every later answer uses it (Q12b, Q15a).
    down = well_status(area="NE-08", not_producing_only=True)
    assert [w["asset_id"] for w in down.rows] == ["WELL-0170", "WELL-0172", "WELL-0175"]
    assert any(n.startswith("WELL-0164 left out") and "Michael Turner" in n for n in down.notes)
    now = well_status(asset_ids=["WELL-0164"]).rows[0]
    assert now["is_producing"] and now["corrections"][0]["corrected_by"] == "Michael Turner"


def test_spill_volume_correction_makes_it_reportable():
    r = record_correction("spill_volume_bbl", 5.4, "field crew measured", asset_id="WELL-0151",
                          date="2026-09-24", config=as_user("U-201"))
    row = r.rows[0]
    assert row["field"] == "spill_est_volume_bbl" and row["kind"] == "ai_analysis"
    assert (row["spill_class_before"], row["spill_class"], row["is_reportable"]) == ("moderate", "reportable", True)
    findings = {f["rule"]: f for f in r.rows[1:]}
    assert findings["SR-01"]["status"] == "breach"
    assert findings["SR-02"]["status"] == "breach" and "6.4 h" in findings["SR-02"]["detail"]
    assert findings["SR-03"]["due_date"] == "2026-11-23"
    assert any("MNT-0151-025" in n and "no longer holds" in n for n in r.notes)

    # Q15b: another user sees it as reportable with the report overdue.
    s = spills(area="NE-08", start="2026-07-18", end="2026-10-16")
    reportable = [x for x in s.rows if x["is_reportable"]]
    assert [x["asset_id"] for x in reportable] == ["WELL-0151"] and reportable[0]["spill_report"] is None
    assert any("INS-0151-0201" in n and "overdue" in n for n in s.notes)


def test_a_second_correction_supersedes_the_first():
    for v in (41.0, 39.0):
        record_correction("wellhead_temp_c", v, "re-measured", inspection_id="INS-0164-0205", config=as_user("U-201"))
    assert [r["status"] for r in db.rows("SELECT status FROM corrections WHERE target_id = 'INS-0164-0205' "
                                         "ORDER BY correction_id")] == ["superseded", "active"]


def test_planned_note_reaches_other_users():
    add_note("WELL-0007", "Shut in from 17 Oct for a 10-day planned workover", "2026-10-17", "2026-10-27",
             config=as_user("U-102"))
    upcoming = well_status(asset_ids=["WELL-0007"]).rows[0]["upcoming_notes"]
    assert upcoming[0]["author_name"] == "Jake Morales" and upcoming[0]["valid_from"] == "2026-10-17"
    notes = [r for r in well_records("WELL-0007", "2026-10-16", "2026-10-16").rows if r["section"] == "notes"]
    assert notes[0]["author_name"] == "Jake Morales"


def test_claims_are_checked_against_the_latest_inspection():
    mine = add_note("WELL-0175", "Shut in for planned work since 14 Oct", "2026-10-14",
                    claims_producing=False, config=as_user("U-201"))
    assert mine.rows[0]["claim_status"] == "consistent"
    theirs = add_note("WELL-0175", "Running fine", claims_producing=True, config=as_user("U-204"))
    assert theirs.rows[0]["claim_status"] == "unconfirmed"
    assert any("INS-0175-0204" in n and "Jessica Reed" in n and "0.4 °C" in n for n in theirs.notes)
    assert any("Michael Turner" in n and "consistent" in n for n in theirs.notes)
    assert any("unconfirmed claim" in n for n in well_status(asset_ids=["WELL-0175"]).notes)


def test_user_rule_applies_at_its_scope_only():
    assert rca("WELL-0120") == ["met"] and rca("WELL-0102") == ["met"]
    r = set_rule("rca_corrective_count", 2, "team wants an RCA after 2 repairs", well_type="T350",
                 config=as_user("U-201"))
    assert r.rows[0]["scope"] == "all T350 wells" and any("T200: 3" in n for n in r.notes)
    assert rca("WELL-0120") == ["open"]       # T350, 2 repairs
    assert rca("WELL-0102") == ["met"]        # T200, 2 repairs: the T200 manual still applies
    detail = next(x["detail"] for x in well_records("WELL-0120", "2025-10-16", "2026-10-16").rows
                  if x.get("rule") == "RCA" and "pump_jack" in x["detail"])
    assert "Michael Turner" in detail
    due = rca_due(area="NE-07", equipment_kind="pump_jack")
    assert [x["asset_id"] for x in due.rows] == ["WELL-0108", "WELL-0120", "WELL-0121", "WELL-0138"]
    assert any(n.startswith("added only because of a user rule") and "WELL-0120" in n and "WELL-0108" not in n
               for n in due.notes)


def test_nothing_is_recorded_without_a_known_user():
    for config in (as_user("U-999"), {"configurable": {}}):
        r = add_note("WELL-0001", "x", config=config)
        assert not r.rows and "not identified" in r.notes[0]
    assert not db.rows("SELECT 1 FROM notes WHERE source = 'copilot'")


def test_bad_arguments_come_back_as_notes():
    u = as_user("U-201")
    assert "nearest: INS-0164-0205" in record_correction("wellhead_temp_c", 41.0, "x", asset_id="WELL-0164",
                                                        date="2026-10-14", config=u).notes[0]
    assert "unknown field" in record_correction("pressure", 1, "x", inspection_id="INS-0164-0205", config=u).notes[0]
    assert "unknown rule_key" in set_rule("foo", 1, "x", config=u).notes[0]
    assert "unknown well_type" in set_rule("rca_corrective_count", 2, "x", well_type="T999", config=u).notes[0]


def test_the_model_cannot_choose_the_author(use_model):  # noqa: F811
    tools = {t.name: t for t in build_tools()}
    for name in ("record_correction", "add_note", "set_rule"):
        props = tools[name].tool_call_schema.model_json_schema()["properties"]
        assert not {"config", "user_id", "author"} & set(props)

    use_model(
        AIMessage("", tool_calls=[call("add_note", {"asset_id": "WELL-0007", "text": "Workover from 17 Oct",
                                                    "valid_from": "2026-10-17"}, "c1")]),
        AIMessage("Noted for everyone."),
    )
    a = api.ask("FYI: WELL-0007 workover from 17 Oct", "U-102", "t-author")
    assert a.error is None and a.tool_calls[0].name == "add_note"
    assert db.rows("SELECT author_user_id, conversation_id FROM notes WHERE source = 'copilot'") == [
        {"author_user_id": "U-102", "conversation_id": "t-author"}]
