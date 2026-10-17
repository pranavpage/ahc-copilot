"""Status tools (A1) on the sample data. No LLM or network calls."""

import pytest

from copilot import results
from copilot.tools.status import downtime, inspection_series, well_status


def by_id(result):
    return {r["asset_id"]: r for r in result.rows}


def test_well_status_one_well():
    r = well_status(asset_ids=["WELL-0001"])
    [row] = r.rows
    assert row["is_producing"] is False
    assert row["temp_delta_c"] == 3.2
    assert row["producing_threshold_c"] == 15
    assert row["inspection_id"] == "INS-0001-0203"
    assert row["inspected_at"].startswith("2026-10-15")
    assert row["inspector_name"] == "Ryan Brooks"
    assert row["method"] == "drone"
    assert row["recorded_status"] == "active"
    assert row["recorded_status_stale"] is True
    assert "CTX-0001-003" in [n["note_id"] for n in row["current_notes"]]
    assert "reason" not in row
    assert {"INS-0001-0203", "CTX-0001-003"} <= set(r.ids)
    assert any(i.startswith("T200 § ") for i in r.ids)


def test_well_status_area_not_producing():
    r = well_status(area="Northeast Block 8", not_producing_only=True)
    rows = by_id(r)
    assert sorted(rows) == ["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"]
    assert [m["maintenance_id"] for m in rows["WELL-0170"]["open_repairs"]] == ["MNT-0170-031"]
    assert [m["maintenance_id"] for m in rows["WELL-0172"]["open_repairs"]] == ["MNT-0172-028"]
    assert {"MNT-0170-031", "MNT-0172-028"} <= set(r.ids)
    for well in ("WELL-0164", "WELL-0175"):
        assert "reason" in rows[well] and rows[well]["reason"] is None
        assert any(n.startswith(f"{well}: no recorded reason") for n in r.notes)
    assert all(row["area_name"] == "Northeast Block 8" for row in r.rows)


def test_well_status_area_id_same_as_name():
    by_name = well_status(area="Northeast Block 8")
    by_area_id = well_status(area="NE-08")
    assert by_name.rows and sorted(by_id(by_name)) == sorted(by_id(by_area_id))


def test_well_status_unknown_area():
    r = well_status(area="Nowhere")
    assert r.rows == []
    [note] = r.notes
    assert note.startswith("unknown area 'Nowhere'; valid: ")
    assert "Northeast Block 8" in note


def test_well_status_unknown_well():
    r = well_status(asset_ids=["WELL-9999"])
    assert r.rows == [] and any("WELL-9999" in n for n in r.notes)


def test_well_status_all_wells_capped():
    r = well_status()
    assert 0 < len(r.rows) <= 200


def test_inspection_series():
    r = inspection_series("WELL-0001", "2026-07-17", "2026-10-16")
    assert len(r.rows) == 13
    assert r.rows[0]["inspected_date"] == "2026-07-23"
    dates = [row["inspected_date"] for row in r.rows]
    assert dates == sorted(dates)
    assert [row["inspected_date"] for row in r.rows if not row["is_producing"]] == [
        "2026-10-08",
        "2026-10-15",
    ]
    assert {row["inspection_id"] for row in r.rows} <= set(r.ids)


def test_inspection_series_bad_input():
    assert inspection_series("WELL-9999", "2026-07-17", "2026-10-16").rows == []
    r = inspection_series("WELL-0001", "17 July", "2026-10-16")
    assert r.rows == [] and r.notes


def test_downtime_one_well():
    r = downtime("2025-01-01", "2025-12-31", asset_id="WELL-0001")
    [row] = r.rows
    assert row["downtime_days"] == 21
    assert row["down_inspections"] == 3
    assert row["down_dates"] == ["2025-07-24", "2025-10-16", "2025-10-23"]
    assert set(row["down_inspection_ids"]) <= set(r.ids)
    assert any(n.startswith("downtime = days per not-producing inspection (7 from ") for n in r.notes)


def test_downtime_top_n_area():
    r = downtime("2026-06-16", "2026-10-16", area="Northeast Block 7", top_n=3)
    got = [(row["asset_id"], row["downtime_days"]) for row in r.rows]
    # Ties are ordered by asset_id (the brief's verified list had WELL-0138 before WELL-0107).
    assert got == [("WELL-0121", 49), ("WELL-0107", 42), ("WELL-0138", 42)]


def test_downtime_keeps_ties_at_cut():
    r = downtime("2026-06-16", "2026-10-16", area="Northeast Block 7", top_n=2)
    assert [row["asset_id"] for row in r.rows] == ["WELL-0121", "WELL-0107", "WELL-0138"]


def test_downtime_unknown_area():
    r = downtime("2026-06-16", "2026-10-16", area="Nowhere")
    assert r.rows == [] and r.notes[0].startswith("unknown area 'Nowhere'; valid: ")


@pytest.mark.parametrize(
    "call",
    [
        lambda: well_status(asset_ids=["WELL-0001"]),
        lambda: well_status(area="Nowhere"),
        lambda: inspection_series("WELL-0001", "2026-07-17", "2026-10-16"),
        lambda: downtime("2025-01-01", "2025-12-31", asset_id="WELL-0001"),
    ],
)
def test_results_stored(call):
    r = call()
    assert r.result_id
    assert results.get(r.result_id) == r.rows


def test_downtime_one_well_explains_each_stop():
    from copilot.tools.status import downtime

    w = downtime("2025-01-01", "2025-12-31", asset_id="WELL-0001").rows[0]
    assert w["downtime_days"] == 21
    first = w["down_details"][0]
    assert (first["wellhead_temp_c"], first["ambient_temp_c"], first["temp_delta_c"]) == (51.6, 43.1, 8.5)
    assert [m["maintenance_id"] for d in w["down_details"] for m in d["repairs"]] == [
        "MNT-0001-021", "MNT-0001-023", "MNT-0001-023"]
