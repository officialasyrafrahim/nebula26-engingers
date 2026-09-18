"""Eight-CSV parsing and canonical PlanningInstance validation (AT-01)."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.domain.rail.errors import InstanceParseError, InstanceValidationError
from app.domain.rail.instance_model import PlanningInstance
from app.modules.instance.parser import parse_mapping
from app.modules.instance.schemas import INSTANCE_FILES
from tests.helpers_rail import (
    instance_from_source,
    load_public_instance,
    parse_public,
    read_instance_source,
)


def test_public_instance_parses_with_expected_counts():
    parsed = parse_public()
    assert len(parsed.lines) == 2
    assert len(parsed.stations) == 20
    assert len(parsed.sectors) == 18
    assert len(parsed.locations) == 76
    assert len(parsed.buffer_rules) == 3
    assert len(parsed.contracts) == 14
    assert len(parsed.activities) == 54
    assert parsed.parameters.horizon_start.isoformat() == "2027-01-04"
    assert parsed.parameters.horizon_weeks == 30


def test_canonical_instance_is_valid_and_frozen():
    instance = load_public_instance()
    assert isinstance(instance, PlanningInstance)
    assert instance.lines["ALP"].line_name == "Line Alpha"
    assert ("ALP", "H01") in instance.stations
    assert ("BET", "H01") in instance.stations
    assert instance.activities["A004"].predecessor_activity_id == "A003"
    assert instance.successors["A003"] == ("A004",)
    with pytest.raises(ValidationError):
        instance.horizon_weeks = 99  # type: ignore[misc]


def test_blank_predecessor_becomes_none():
    parsed = parse_public()
    by_id = {activity.activity_id: activity for activity in parsed.activities}
    assert by_id["A002"].predecessor_activity_id is None
    assert by_id["A013"].predecessor_activity_id == "A012"


def test_missing_file_is_reported_per_file():
    source = read_instance_source()
    del source["03_SECTORS.csv"]
    with pytest.raises(InstanceParseError) as excinfo:
        parse_mapping(source)
    messages = [str(issue) for issue in excinfo.value.issues]
    assert any("03_SECTORS.csv" in message and "missing" in message for message in messages)


def test_unexpected_file_is_rejected():
    source = read_instance_source()
    source["09_EXTRA.csv"] = "a,b\n1,2\n"
    with pytest.raises(InstanceParseError) as excinfo:
        parse_mapping(source)
    assert any("09_EXTRA.csv" in str(issue) for issue in excinfo.value.issues)


@pytest.mark.parametrize(
    "bad_header, fragmenents",
    [
        ("line_code", ["line_name", "missing"]),
        ("line_code,line_name,extra", ["extra", "unexpected"]),
        ("line_name,line_code", ["order"]),
    ],
)
def test_bad_headers_report_column_problems(bad_header, fragmenents):
    source = read_instance_source()
    source["01_LINES.csv"] = bad_header + "\nALP,Line Alpha\nBET,Line Beta\n"
    with pytest.raises(InstanceParseError) as excinfo:
        parse_mapping(source)
    rendered = "\n".join(str(issue) for issue in excinfo.value.issues)
    for fragment in fragmenents:
        assert fragment in rendered


def test_bad_row_value_reports_file_row_and_column():
    source = read_instance_source()
    source["02_STATIONS.csv"] = source["02_STATIONS.csv"].replace("S01,ALP,1,0", "S01,ALP,x,0")
    with pytest.raises(InstanceParseError) as excinfo:
        parse_mapping(source)
    issues = excinfo.value.issues
    row_issue = next(issue for issue in issues if issue.row is not None)
    assert row_issue.file == "02_STATIONS.csv"
    assert row_issue.row == 2
    assert row_issue.column == "seq"


def test_missing_parameter_is_reported():
    source = read_instance_source()
    source["06_PARAMETERS.csv"] = "key,value\nhorizon_start,2027-01-04\n"
    with pytest.raises(InstanceParseError) as excinfo:
        parse_mapping(source)
    assert any("horizon_weeks" in str(issue) for issue in excinfo.value.issues)


def test_unknown_contract_reference_is_rejected():
    source = read_instance_source()
    source["08_ACTIVITY_DETAILS.csv"] = source["08_ACTIVITY_DETAILS.csv"].replace(
        "A001,C001,", "A001,C999,", 1
    )
    with pytest.raises(InstanceValidationError) as excinfo:
        instance_from_source(source)
    assert any("unknown contract" in str(issue) for issue in excinfo.value.issues)


def test_predecessor_cycle_is_rejected():
    source = read_instance_source()
    text = source["08_ACTIVITY_DETAILS.csv"]
    text = text.replace("A001,C001,Renewal,SEC:BET:S15_S16:EB,SEC:BET:S16_S17:EB,2,2027-05-24,,2",
                        "A001,C001,Renewal,SEC:BET:S15_S16:EB,SEC:BET:S16_S17:EB,2,2027-05-24,A002,2")
    text = text.replace("A002,C001,Renewal,SEC:BET:S11_S12:WB,SEC:BET:S12_S13:WB,1,2027-01-04,,3",
                        "A002,C001,Renewal,SEC:BET:S11_S12:WB,SEC:BET:S12_S13:WB,1,2027-01-04,A001,3")
    source["08_ACTIVITY_DETAILS.csv"] = text
    with pytest.raises(InstanceValidationError) as excinfo:
        instance_from_source(source)
    assert any("cycle" in str(issue) for issue in excinfo.value.issues)


def test_duplicate_records_are_rejected():
    source = read_instance_source()
    source["01_LINES.csv"] = "line_code,line_name\nALP,Line Alpha\nALP,Line Alpha Again\n"
    with pytest.raises(InstanceValidationError) as excinfo:
        instance_from_source(source)
    assert any("duplicate line" in str(issue) for issue in excinfo.value.issues)


def test_activity_type_mismatch_is_rejected():
    source = copy.deepcopy(read_instance_source())
    source["08_ACTIVITY_DETAILS.csv"] = source["08_ACTIVITY_DETAILS.csv"].replace(
        "A001,C001,Renewal,", "A001,C001,Construction,", 1
    )
    with pytest.raises(InstanceValidationError) as excinfo:
        instance_from_source(source)
    assert any("activity_type" in str(issue) for issue in excinfo.value.issues)


def test_all_eight_files_are_required():
    source = read_instance_source()
    assert set(source) == set(INSTANCE_FILES)
