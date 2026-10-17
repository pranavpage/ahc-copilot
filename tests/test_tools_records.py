"""Record tools (A2) against the sample data. No LLM or network calls."""

import pytest

from copilot import results
from copilot.tools.records import rca_due, repair_costs, search_docs, spills, well_records


def by_asset(rows):
    return {r["asset_id"]: r for r in rows}


# ----------------------------------------------------------------------------
# spills
# ----------------------------------------------------------------------------

def test_spills_one_well_total_and_cancelled_note():
    r = spills(asset_id="WELL-0001")
    assert len(r.rows) == 6
    assert round(sum(x["spill_volume_bbl"] for x in r.rows), 2) == 15.1
    assert any("INS-0001-0070" in n and "COR-CTX-0001-001" in n for n in r.notes)
    assert "INS-0001-0070" not in {x["inspection_id"] for x in r.rows}
    assert {"INS-0001-0185", "COR-CTX-0001-001"} <= set(r.ids)
    assert results.get(r.result_id) == r.rows


def test_spills_area_by_name_with_location():
    r = spills(start="2026-07-18", end="2026-10-16", area="Northeast Block 8")
    got = by_asset(r.rows)
    assert {k: v["spill_volume_bbl"] for k, v in got.items()} == {
        "WELL-0151": 4.5, "WELL-0165": 1.2, "WELL-0175": 3.9, "WELL-0186": 0.6,
    }
    assert all(x["lat"] is not None and x["lon"] is not None for x in r.rows)
    assert all(x["area_name"] == "Northeast Block 8" for x in r.rows)


def test_spills_group_by_area():
    r = spills(start="2026-01-01", end="2026-12-31", group_by=["area"])
    counts = {x["area"]: x["spill_count"] for x in r.rows}
    assert counts == {
        "Southwest Block 23": 35, "Southwest Block 24": 43,
        "Northeast Block 7": 37, "Northeast Block 8": 26,
    }
    assert all(set(x) == {"area", "spill_count", "total_bbl"} for x in r.rows)


def test_spills_group_by_area_month():
    r = spills(start="2026-01-01", end="2026-12-31", group_by=["area", "month"])
    assert all(len(x["month"]) == 7 and x["month"].startswith("2026-") for x in r.rows)
    assert sum(x["spill_count"] for x in r.rows) == 35 + 43 + 37 + 26


def test_spills_area_by_id_containment():
    r = spills(start="2026-07-18", end="2026-10-16", area="SW-24")
    late = {x["asset_id"]: (x["maintenance_id"], x["containment_hours"])
            for x in r.rows if x["contained_in_time"] is False}
    assert late == {"WELL-0082": ("MNT-0082-028", 7.1), "WELL-0100": ("MNT-0100-034", 8.1)}
    assert all(x["containment_limit_hours"] is not None for x in r.rows)
    assert any("§" in i for i in r.ids)


def test_spills_single_day():
    r = spills(asset_id="WELL-0151", start="2026-09-24", end="2026-09-24")
    assert len(r.rows) == 1
    row = r.rows[0]
    assert row["inspection_id"] == "INS-0151-0201"
    assert row["spill_volume_bbl"] == 4.5
    assert row["spill_class"] == "moderate"
    assert row["containment_hours"] == 6.4
    assert row["contained_in_time"] is False
    assert "raw_spill_est_volume_bbl" not in row


@pytest.mark.parametrize("kwargs, note", [
    ({"area": "Atlantis"}, "unknown area 'Atlantis'; valid: "),
    ({"asset_id": "WELL-9999"}, "unknown well"),
    ({"start": "16/10/2026"}, "bad start date"),
    ({"start": "2026-10-16", "end": "2026-01-01"}, "after end"),
    ({"group_by": ["planet"]}, "unknown group_by"),
])
def test_spills_bad_input_returns_note(kwargs, note):
    r = spills(**kwargs)
    assert r.rows == [] and any(note in n for n in r.notes)


def test_spills_unknown_area_lists_names():
    r = spills(area="Atlantis")
    assert "Northeast Block 8" in r.notes[0]


# ----------------------------------------------------------------------------
# well_records
# ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def well_0001():
    return well_records("WELL-0001", "2025-10-16", "2026-10-16")


def findings(r, rule):
    return [x for x in r.rows if x["section"] == "findings" and x["rule"] == rule]


def test_well_records_sections(well_0001):
    sections = [x["section"] for x in well_0001.rows]
    assert {"findings", "repairs", "events", "report_findings", "notes"} <= set(sections)
    # grouped by section
    assert sections == sorted(sections, key=sections.index)
    repairs = [x for x in well_0001.rows if x["section"] == "repairs"]
    assert all("2025-10-16" <= x["date"] <= "2026-10-16" for x in repairs)
    assert [x["date"] for x in repairs] == sorted(x["date"] for x in repairs)
    assert any(x["report_path"] and x["containment_hours"] for x in repairs)
    report = [x for x in well_0001.rows if x["section"] == "report_findings"]
    assert report and all(x["result"] != "Met" for x in report)


def test_well_records_sr01(well_0001):
    [f] = findings(well_0001, "SR-01")
    assert f["status"] == "breach"
    assert "REG-0001-001" in f["ids"] and "41" in f["detail"]


def test_well_records_sr02(well_0001):
    breaches = [f for f in findings(well_0001, "SR-02") if f["status"] == "breach"]
    assert len(breaches) == 1
    assert "INS-0001-0185" in breaches[0]["ids"] and "7 h" in breaches[0]["detail"]


def test_well_records_sr03(well_0001):
    [f] = findings(well_0001, "SR-03")
    assert f["status"] == "breach"
    assert f["due_date"] == "2026-08-10"
    assert "REG-0001-003" in f["ids"] and "REG-0001-003 open" in f["detail"]


def test_well_records_rc04(well_0001):
    [f] = findings(well_0001, "RC-04")
    assert f["status"] == "breach"
    assert f["ids"] == ["REG-0001-002"]
    assert "no nov_response_filed" in f["detail"]


def test_well_records_rca(well_0001):
    [f] = [f for f in findings(well_0001, "RCA") if f["status"] == "open"]
    assert f["ids"] == ["MNT-0001-028", "MNT-0001-029", "MNT-0001-032"]
    assert "flowline" in f["detail"]


def test_well_records_rc02(well_0001):
    by_year = {f["due_date"][:4]: f for f in findings(well_0001, "RC-02")}
    assert by_year["2026"]["status"] == "met"
    assert by_year["2026"]["ids"] == ["MNT-0001-026"]


def test_well_records_cites_rules(well_0001):
    assert "spill-response-sop §4. Protocols" in well_0001.ids
    assert any(i.startswith("regulatory-compliance-sop §") for i in well_0001.ids)
    assert {"REG-0001-001", "REG-0001-002", "REG-0001-003", "MNT-0001-028"} <= set(well_0001.ids)


def test_well_records_includes_open_events_outside_window():
    r = well_records("WELL-0001", "2026-10-01", "2026-10-16")
    events = {x["event_id"] for x in r.rows if x["section"] == "events"}
    assert {"REG-0001-002", "REG-0001-003"} <= events
    assert "REG-0001-001" not in events


def test_well_records_bad_input():
    assert well_records("WELL-9999", "2026-01-01", "2026-10-16").notes == ["unknown well 'WELL-9999'"]
    assert well_records("WELL-0001", "2026-13-01", "2026-10-16").rows == []


# ----------------------------------------------------------------------------
# search_docs
# ----------------------------------------------------------------------------

def test_search_docs_sop_section():
    r = search_docs("contained within hours")
    assert "spill-response-sop §4. Protocols" in [x["cite"] for x in r.rows]
    assert all({"kind", "ref_id", "asset_id", "heading", "snippet"} <= set(x) for x in r.rows)


def test_search_docs_manual_section():
    r = search_docs("T350 production temperature")
    assert "T350 §3. Production temperature rule" in [x["cite"] for x in r.rows]
    assert "T350 §3. Production temperature rule" in r.ids


@pytest.mark.parametrize("query", ['"; DROP', "NEAR(", "a AND OR NOT", "*", ""])
def test_search_docs_fts_syntax_is_safe(query):
    r = search_docs(query)
    assert isinstance(r.rows, list)


def test_search_docs_asset_filter():
    r = search_docs("flowline leak", asset_id="WELL-0001", limit=20)
    assert r.rows and all(x["asset_id"] in (None, "WELL-0001") for x in r.rows)
    assert len(search_docs("flowline", limit=3).rows) == 3


# ----------------------------------------------------------------------------
# filters and context for the answers (Q4, Q8, Q9, Q10, Q18)
# ----------------------------------------------------------------------------

def test_spills_cancelled_note_gives_the_reason():
    note = next(n for n in spills(asset_id="WELL-0001").notes if "cancelled" in n)
    assert "INS-0001-0070" in note and "CTX-0001-001" in note and "rainwater" in note


def test_spills_not_contained_only():
    r = spills(area="SW-24", start="2026-07-18", end="2026-10-16", not_contained_only=True)
    assert [x["asset_id"] for x in r.rows] == ["WELL-0100", "WELL-0082"]
    assert all(x["contained_in_time"] is False for x in r.rows)


def test_spills_carry_the_notes_that_name_them():
    r = spills(asset_id="WELL-0101", start="2026-08-20", end="2026-08-20")
    assert [n["note_id"] for n in r.rows[0]["notes_on_spill"]] == ["CTX-0101-002", "CTX-0101-003"]
    assert {"CTX-0101-002", "CTX-0101-003"} <= set(r.ids)


def test_spills_heatmap_totals_per_area():
    r = spills(start="2026-01-01", end="2026-12-31", group_by=["area", "month"])
    assert any("Southwest Block 24 43" in n and "Northeast Block 8 26" in n for n in r.notes)


def test_well_records_only_findings_with_volume_and_fine():
    r = well_records("WELL-0001", "2025-10-16", "2026-10-16", sections=["findings"])
    assert {x["section"] for x in r.rows} == {"findings"}
    sr01 = next(x for x in r.rows if x["rule"] == "SR-01")
    assert "6.8 bbl" in sr01["detail"]
    assert "fine USD 5000" in next(x for x in r.rows if x["rule"] == "RC-04")["detail"]


# ----------------------------------------------------------------------------
# repair_costs, rca_due (Q11, Q14)
# ----------------------------------------------------------------------------

def test_repair_costs_totals_per_well():
    r = repair_costs(["WELL-0121", "WELL-0138", "WELL-0107"], "2026-01-01", "2026-10-16")
    assert {x["asset_id"]: x["cost_total_usd"] for x in r.rows} == {
        "WELL-0121": 25794, "WELL-0138": 46942, "WELL-0107": 5176}
    assert "unknown" in repair_costs(["WELL-9999"], "2026-01-01", "2026-10-16").notes[0]


def test_rca_due_pump_jack_ne07():
    r = rca_due(area="Northeast Block 7", equipment_kind="pump_jack")
    assert [x["asset_id"] for x in r.rows] == ["WELL-0108", "WELL-0121", "WELL-0138"]
    assert all(x["corrective_repairs"] >= x["rca_limit"] for x in r.rows)
    assert "T200: 3" in r.notes[0] and "T350: 3" in r.notes[0]
