"""Well lookup on the sample data. No LLM or network calls."""

import json

import pytest

from copilot.agent import data_tool
from copilot.tools.status import downtime
from copilot.tools.wells import identify_well, well_id


@pytest.mark.parametrize("text", ["WELL-0001", "well-0001", "0001", "1", "well 1", "W-1", "w0001", "#1",
                                  "SW-23 Well 001"])
def test_well_id_forms(text):
    assert well_id(text) == "WELL-0001"


@pytest.mark.parametrize("text", ["", "9999", "WELL-9999", "pump jack", "NE-08"])
def test_well_id_unknown(text):
    assert well_id(text) is None


def test_identify_well_metadata():
    r = identify_well("0001")
    [row] = r.rows
    assert row["asset_id"] == "WELL-0001"
    assert row["well_type"] == "T200"
    assert row["manual"] == "T200"
    assert row["area_name"] == "Southwest Block 23"
    assert row["recorded_status"] == "active"
    assert "WELL-0001" in r.ids
    assert r.notes == []


def test_identify_well_several_and_unknown():
    r = identify_well("0001, well 164 and 9999")
    assert [row["asset_id"] for row in r.rows] == ["WELL-0001", "WELL-0164"]
    assert r.notes == ["no well matches '9999'; well IDs look like WELL-0001"]


def test_agent_cleans_well_args():
    """The screenshot bug: downtime(asset_id="0001") said "no downtime" for a real well."""
    tool = data_tool(downtime)
    content, artifact = tool.func(start="2025-01-01", end="2025-12-31", asset_id="0001")
    out = json.loads(content)
    assert "'0001' read as WELL-0001" in out["notes"]
    assert [r["asset_id"] for r in out["rows"]] == ["WELL-0001"]
    assert out["rows"][0]["downtime_days"] == 21
