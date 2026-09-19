"""Hidden-instance hardening for the instance, domain and compiler paths.

Each test pins one strictness guarantee the published PS1 format implies: exact
CSV quoting, UTF-8 decoding, canonical scalar spellings, network adjacency,
location-kind agreement and closure-location completeness. Success tests prove
the public instance still parses and compiles unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.domain.rail.errors import InstanceParseError, InstanceValidationError
from app.domain.rail.instance_model import find_predecessor_cycles
from app.modules.compiler.closures import ClosureError
from app.modules.compiler.rule_compiler import compile_instance
from app.modules.instance.parser import parse_directory, parse_mapping
from tests.helpers_rail import (
    instance_from_source,
    load_public_compiled,
    load_public_instance,
    parse_public,
    read_instance_source,
)
from tests.test_rail_solver import make_planning


def _parse_issues(source: Mapping[str, object]):
    with pytest.raises(InstanceParseError) as excinfo:
        parse_mapping(source)
    return excinfo.value.issues


def _validation_issues(source: Mapping[str, object]):
    with pytest.raises(InstanceValidationError) as excinfo:
        instance_from_source(source)
    return excinfo.value.issues


def _live_planning(start: str, end: str):
    return make_planning(
        [{"contract_number": "C1", "access_type": "C", "nature_of_activity": "Live"}],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": start,
                "end_location_id": end,
                "total_accesses": 1,
            }
        ],
    )


def test_public_instance_still_parses_and_compiles():
    parsed = parse_public()
    assert parsed.parameters.horizon_start.isoformat() == "2027-01-04"
    assert parsed.parameters.horizon_weeks == 30
    instance = load_public_instance()
    compiled = load_public_compiled()
    assert len(compiled.activities) == len(instance.activities)


def test_exact_boolean_and_integer_spellings_are_accepted():
    parsed = parse_public()
    interchange = next(station for station in parsed.stations if station.station_id == "H01")
    assert interchange.is_interchange is True
    regular = [station for station in parsed.stations if station.station_id == "S01"]
    assert regular and all(not station.is_interchange for station in regular)
    assert parsed.buffer_rules[0].up_to_buffer_sectors == 2


def test_unclosed_quoted_field_is_rejected():
    source = read_instance_source()
    source["01_LINES.csv"] = 'line_code,line_name\nALP,"Line Alpha\n'
    issues = _parse_issues(source)
    assert any(
        issue.file == "01_LINES.csv" and "malformed CSV" in issue.message for issue in issues
    )


def test_malformed_quoted_field_is_rejected():
    source = read_instance_source()
    source["01_LINES.csv"] = 'line_code,line_name\nALP,"Line Alpha"x\n'
    issues = _parse_issues(source)
    assert any(
        issue.file == "01_LINES.csv" and "malformed CSV" in issue.message for issue in issues
    )


def test_invalid_utf8_is_a_structured_issue():
    source = read_instance_source()
    source["01_LINES.csv"] = b"\xff\xfe not utf-8"
    issues = _parse_issues(source)
    issue = next(issue for issue in issues if issue.file == "01_LINES.csv")
    assert "UTF-8" in issue.message


def test_invalid_utf8_in_directory_is_a_structured_issue(tmp_path):
    for name, text in read_instance_source().items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "02_STATIONS.csv").write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(InstanceParseError) as excinfo:
        parse_directory(tmp_path)
    assert any(
        issue.file == "02_STATIONS.csv" and "UTF-8" in issue.message
        for issue in excinfo.value.issues
    )


@pytest.mark.parametrize("spelling", ["01", "1.0", "+1", "1_0"])
def test_non_canonical_integer_spelling_is_rejected(spelling):
    source = read_instance_source()
    source["02_STATIONS.csv"] = source["02_STATIONS.csv"].replace(
        "S01,ALP,1,0", f"S01,ALP,{spelling},0"
    )
    issues = _parse_issues(source)
    assert any(issue.column == "seq" for issue in issues)


@pytest.mark.parametrize(
    "spelling", ["2027-1-4", "20270104", "2027-01-04T00:00:00", "04-01-2027"]
)
def test_non_canonical_date_spelling_is_rejected(spelling):
    source = read_instance_source()
    source["06_PARAMETERS.csv"] = (
        f"key,value\nhorizon_start,{spelling}\nhorizon_weeks,30\n"
    )
    issues = _parse_issues(source)
    assert any(
        issue.file == "06_PARAMETERS.csv" and issue.column == "horizon_start"
        for issue in issues
    )


@pytest.mark.parametrize("spelling", ["true", "false", "True", "yes", "2"])
def test_non_binary_boolean_spelling_is_rejected(spelling):
    source = read_instance_source()
    source["02_STATIONS.csv"] = source["02_STATIONS.csv"].replace(
        "S01,ALP,1,0", f"S01,ALP,1,{spelling}"
    )
    issues = _parse_issues(source)
    assert any(issue.column == "is_interchange" for issue in issues)


def test_access_type_must_be_pm_pc_or_c():
    source = read_instance_source()
    source["07_PROJECT_DETAILS.csv"] = source["07_PROJECT_DETAILS.csv"].replace(
        "2026-10-02,Renewal,Non-live (Consist),3,2027-08-01,2027-06-13,2,C,3",
        "2026-10-02,Renewal,Non-live (Consist),3,2027-08-01,2027-06-13,2,X,3",
    )
    issues = _parse_issues(source)
    assert any(issue.column == "access_type" for issue in issues)


def test_long_predecessor_chain_has_no_cycle_and_no_recursion_error():
    chain = {f"A{i:05d}": f"A{i - 1:05d}" for i in range(1, 5000)}
    assert find_predecessor_cycles(chain) == []


def test_long_predecessor_chain_cycle_is_detected_iteratively():
    chain = {f"A{i:05d}": f"A{i - 1:05d}" for i in range(1, 5000)}
    chain["A00000"] = "A04999"
    cycles = find_predecessor_cycles(chain)
    assert len(cycles) == 1
    assert len(cycles[0]) == 5000


def test_sector_id_endpoint_mismatch_is_rejected():
    source = read_instance_source()
    source["03_SECTORS.csv"] = source["03_SECTORS.csv"].replace(
        "SEC:ALP:S01_S02,ALP,S01,S02,1,0",
        "SEC:ALP:S01_S03,ALP,S01,S02,1,0",
    )
    issues = _validation_issues(source)
    assert any("sector" in issue.message and "disagrees" in issue.message for issue in issues)


def test_non_adjacent_sector_endpoints_are_rejected():
    source = read_instance_source()
    source["03_SECTORS.csv"] = source["03_SECTORS.csv"].replace(
        "SEC:ALP:S01_S02,ALP,S01,S02,1,0",
        "SEC:ALP:S01_S03,ALP,S01,S03,1,0",
    )
    issues = _validation_issues(source)
    assert any("adjacent" in issue.message for issue in issues)


def test_location_kind_must_match_location_id_kind():
    source = read_instance_source()
    source["04_LOCATION_SUPPLY.csv"] = source["04_LOCATION_SUPPLY.csv"].replace(
        "PLAT:ALP:S01:EB,platform sector,ALP,EB,2",
        "PLAT:ALP:S01:EB,tunnel sector,ALP,EB,2",
    )
    issues = _validation_issues(source)
    assert any("location_kind" in issue.message for issue in issues)


def test_unknown_location_kind_is_rejected():
    source = read_instance_source()
    source["04_LOCATION_SUPPLY.csv"] = source["04_LOCATION_SUPPLY.csv"].replace(
        "PLAT:ALP:S01:EB,platform sector,ALP,EB,2",
        "PLAT:ALP:S01:EB,platform,ALP,EB,2",
    )
    issues = _parse_issues(source)
    assert any(issue.column == "location_kind" for issue in issues)


def test_missing_buffer_closure_location_is_rejected():
    instance = _live_planning("SEC:ALP:S01_S02:EB", "SEC:ALP:S01_S02:EB")
    locations = {
        key: value for key, value in instance.locations.items() if key != "PLAT:ALP:H01:EB"
    }
    instance = instance.model_copy(update={"locations": locations})
    with pytest.raises(ClosureError) as excinfo:
        compile_instance(instance)
    assert "buffer closure" in str(excinfo.value)
    assert "PLAT:ALP:H01:EB" in str(excinfo.value)


def test_missing_opposite_bound_location_is_rejected():
    instance = _live_planning("SEC:ALP:S01_S02:EB", "SEC:ALP:S01_S02:EB")
    locations = {
        key: value
        for key, value in instance.locations.items()
        if key != "SEC:ALP:S01_S02:WB"
    }
    instance = instance.model_copy(update={"locations": locations})
    with pytest.raises(ClosureError) as excinfo:
        compile_instance(instance)
    assert "opposite-bound mirror" in str(excinfo.value)


def test_missing_interchange_location_is_rejected():
    instance = _live_planning("SEC:ALP:H01_H02:EB", "SEC:ALP:H01_H02:EB")
    locations = {
        key: value for key, value in instance.locations.items() if key != "PLAT:BET:H01:EB"
    }
    instance = instance.model_copy(update={"locations": locations})
    with pytest.raises(ClosureError) as excinfo:
        compile_instance(instance)
    assert "interchange closure" in str(excinfo.value)
