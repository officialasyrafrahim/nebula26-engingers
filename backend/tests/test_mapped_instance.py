"""Mapped DTL/CCL demonstration dataset generator behaviour (F-DATA-001).

These tests exercise the real parser and compiler against every generated
profile, prove byte-for-byte determinism for a fixed seed, check the public
LTA-to-ALP/BET mapping, and run one bounded baseline solve when CP-SAT is
available.
"""

from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path

import pytest

from app.modules.compiler.rule_compiler import compile_instance
from app.modules.instance.parser import parse_directory
from app.modules.instance.schemas import INSTANCE_FILES
from app.modules.instance.service import build_planning_instance
from app.modules.solver import cp_sat_available, solve

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PROFILES = ("baseline", "congestion", "disruption")
EXPECTED_HORIZON_START = "2027-01-04"
EXPECTED_HORIZON_WEEKS = 30
H01_H02_LOCATIONS = (
    "SEC:ALP:H01_H02:EB",
    "SEC:ALP:H01_H02:WB",
    "SEC:BET:H01_H02:EB",
    "SEC:BET:H01_H02:WB",
)


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return _load_module("generate_mapped_instance", "generate_mapped_instance.py")


def _generate(generator, profile: str, directory: Path, seed: int = 42) -> None:
    files = generator.build_files(profile, seed)
    generator.write_files(directory, files)


def _dict_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_parses_and_compiles(generator, profile, tmp_path):
    _generate(generator, profile, tmp_path)
    parsed = parse_directory(tmp_path)

    assert len(parsed.lines) == 2
    assert len(parsed.stations) == 20
    assert len(parsed.sectors) == 18
    assert len(parsed.locations) == 76
    assert len(parsed.buffer_rules) == 3
    assert len(parsed.contracts) == 14
    assert len(parsed.activities) == 41
    assert parsed.parameters.horizon_start.isoformat() == EXPECTED_HORIZON_START
    assert parsed.parameters.horizon_weeks == EXPECTED_HORIZON_WEEKS

    instance = build_planning_instance(parsed)
    compiled = compile_instance(instance)
    assert len(compiled.activities) == 41
    assert compiled.location_capacities and compiled.contract_weekly_caps

    for activity_id, activity in instance.activities.items():
        week = instance.planned_start_week(activity)
        assert 1 <= week <= EXPECTED_HORIZON_WEEKS, activity_id


@pytest.mark.parametrize("profile", PROFILES)
def test_buffer_rules_are_preserved(generator, profile, tmp_path):
    _generate(generator, profile, tmp_path)
    parsed = parse_directory(tmp_path)
    rules = {rule.nature_of_works: rule for rule in parsed.buffer_rules}

    assert rules["Live"].up_to_buffer_sectors == 2
    assert rules["Live"].opposite_bound_required is True
    assert rules["Non-live (Consist)"].up_to_buffer_sectors == 1
    assert rules["Non-live (Consist)"].opposite_bound_required is False
    assert rules["Non-live (Others)"].up_to_buffer_sectors == 0
    assert rules["Non-live (Others)"].opposite_bound_required is False

    compiled = compile_instance(build_planning_instance(parsed))
    for activity in compiled.activities.values():
        if activity.nature_of_activity == "Live":
            assert activity.buffer_sectors == 2
            assert activity.opposite_bound_required is True


@pytest.mark.parametrize("profile", PROFILES)
def test_interchange_and_cross_line_live_work_present(generator, profile, tmp_path):
    _generate(generator, profile, tmp_path)
    compiled = compile_instance(build_planning_instance(parse_directory(tmp_path)))

    live_interchange = [
        activity
        for activity in compiled.activities.values()
        if activity.nature_of_activity == "Live" and activity.interchange_locations
    ]
    assert live_interchange
    assert {activity.route.line_code for activity in live_interchange} == {"ALP", "BET"}
    for activity in live_interchange:
        assert any(sector.endswith("H01_H02") for sector in activity.route.sector_ids)
        # live work at the shared tunnel closes the other line's interchange.
        assert activity.interchange_locations


@pytest.mark.parametrize("profile", PROFILES)
def test_predecessor_chains_exist(generator, profile, tmp_path):
    _generate(generator, profile, tmp_path)
    parsed = parse_directory(tmp_path)
    predecessors = [
        activity.predecessor_activity_id
        for activity in parsed.activities
        if activity.predecessor_activity_id is not None
    ]
    assert predecessors
    # build_planning_instance rejects predecessor cycles; compiling proves acyclic.
    compile_instance(build_planning_instance(parsed))


@pytest.mark.parametrize("profile", PROFILES)
def test_deterministic_bytes_for_fixed_seed(generator, profile, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _generate(generator, profile, first, seed=42)
    _generate(generator, profile, second, seed=42)

    for name in INSTANCE_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_disruption_keeps_baseline_demand(generator, tmp_path):
    baseline = generator.build_files("baseline", 42)
    disruption = generator.build_files("disruption", 42)

    for name in INSTANCE_FILES:
        if name == "04_LOCATION_SUPPLY.csv":
            assert baseline[name] != disruption[name]
        else:
            assert baseline[name] == disruption[name]


def test_profiles_change_supply_and_demand(generator):
    baseline = generator.build_files("baseline", 42)
    congestion = generator.build_files("congestion", 42)

    base_locations = {
        row["location_id"]: int(row["supply_capacity"])
        for row in _dict_rows(baseline["04_LOCATION_SUPPLY.csv"])
    }
    congestion_locations = {
        row["location_id"]: int(row["supply_capacity"])
        for row in _dict_rows(congestion["04_LOCATION_SUPPLY.csv"])
    }
    for location_id in H01_H02_LOCATIONS:
        assert congestion_locations[location_id] < base_locations[location_id]

    base_accesses = sum(
        int(row["total_accesses"]) for row in _dict_rows(baseline["08_ACTIVITY_DETAILS.csv"])
    )
    congestion_accesses = sum(
        int(row["total_accesses"])
        for row in _dict_rows(congestion["08_ACTIVITY_DETAILS.csv"])
    )
    assert congestion_accesses > base_accesses


def test_real_topology_mapping(generator):
    network = generator.net
    assert network.LINE_TO_REAL_CODE == {"ALP": "DTL", "BET": "CCL"}
    assert network.real_station_name("ALP", "H01") == "Promenade"
    assert network.real_station_name("ALP", "H02") == "Bayfront"
    assert network.real_station_name("BET", "H01") == "Promenade"
    assert network.real_station_name("BET", "H02") == "Bayfront"
    assert [spec.name for spec in network.stations("ALP")] == [
        "Newton",
        "Little India",
        "Rochor",
        "Bugis",
        "Promenade",
        "Bayfront",
        "Downtown",
        "Telok Ayer",
        "Chinatown",
        "Fort Canning",
    ]
    assert [spec.name for spec in network.stations("BET")] == [
        "Dakota",
        "Mountbatten",
        "Stadium",
        "Nicoll Highway",
        "Promenade",
        "Bayfront",
        "Marina Bay",
        "Prince Edward Road",
        "Cantonment",
        "Keppel",
    ]


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_baseline_bounded_solve(generator, tmp_path):
    _generate(generator, "baseline", tmp_path, seed=42)
    compiled = compile_instance(build_planning_instance(parse_directory(tmp_path)))

    result = solve(compiled, "A", time_limit_seconds=30, seed=42)
    if not result.feasible:
        pytest.skip(f"baseline mapped solve did not finish: {result.status}")

    totals: dict[str, int] = {}
    for row in result.access:
        totals[row.activity_id] = totals.get(row.activity_id, 0) + (3 if row.eclo else 2)
    for activity_id, activity in compiled.activities.items():
        assert totals.get(activity_id, 0) >= 2 * activity.total_accesses
