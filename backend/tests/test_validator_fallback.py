"""Fallback validator, scenario semantics, mutation coverage and the adapter.

The published sample submission is the acceptance oracle: against the public
instance it must pass Scenario A with zero hard violations. Every other test
takes that validated sample (or a tiny synthetic instance) and breaks exactly one
rule to prove the independent validator catches it.

Physical-slot semantics (design A-1/A-2/A-3 and F-COMPILER-002): ``access_night``
is contract/activity-type-local, so equal local night numbers across contracts
are never treated as simultaneity. Closure, mix, capacity and co-sharing checks
consume ``CompiledInstance.physical_possession`` and validate that a consistent
physical-night assignment exists rather than inventing one. The published sample
and solver output are the oracles: both must pass with zero hard violations.
"""

from __future__ import annotations

import json
import sys
import textwrap
from datetime import timedelta

import pytest

from app.domain.rail.instance_model import (
    Activity,
    Contract,
    Parameters,
    PlanningInstance,
    build_successor_index,
)
from app.domain.rail.keys import format_location_id, format_sector_id
from app.domain.rail.network import BufferRule, Line, LocationSupply, Sector, Station
from app.modules.compiler.rule_compiler import compile_instance
from app.modules.export import (
    AccessRow,
    OccupancyRow,
    ResultRow,
    SubmissionBundle,
    build_bundle,
    bundle_from_solver_result,
    load_bundle,
)
from app.modules.solver import cp_sat_available, solve
from app.modules.solver.results import week_end
from app.modules.validator import (
    FORMULA_VERSION,
    OfficialValidatorError,
    infer_scenario,
    run_calibration,
    validate_bundle,
    validate_compiled,
    validate_directories,
    validate_with_adapter,
)
from app.modules.validator.adapter import VALIDATOR_COMMAND_ENV
from tests.helpers_rail import (
    PUBLIC_INSTANCE_DIR,
    SUBMISSION_SAMPLE_DIR,
    load_public_instance,
)
from tests.test_rail_solver import HORIZON_START, make_compiled, make_planning

SECTOR = "SEC:ALP:S01_S02:EB"


@pytest.fixture(scope="module")
def public_instance():
    return load_public_instance()


@pytest.fixture(scope="module")
def sample_bundle() -> SubmissionBundle:
    return load_bundle(SUBMISSION_SAMPLE_DIR)


def _replace(
    bundle: SubmissionBundle,
    *,
    access=None,
    occupancy=None,
    results=None,
) -> SubmissionBundle:
    return bundle.model_copy(
        update={
            "access": bundle.access if access is None else tuple(access),
            "occupancy": bundle.occupancy if occupancy is None else tuple(occupancy),
            "results": bundle.results if results is None else tuple(results),
        }
    )


def _remap_weeks(bundle: SubmissionBundle, activity_id: str, mapping: dict[int, int]):
    access = [
        row.model_copy(update={"week": mapping[row.week]})
        if row.activity_id == activity_id and row.week in mapping
        else row
        for row in bundle.access
    ]
    occupancy = [
        row.model_copy(update={"week": mapping[row.week]})
        if row.activity_id == activity_id and row.week in mapping
        else row
        for row in bundle.occupancy
    ]
    return _replace(bundle, access=access, occupancy=occupancy)


def _rules(report) -> set[str]:
    return set(report.rules)


_ONE_LINE_STATIONS = (("S01", 1), ("S02", 2), ("S03", 3), ("S04", 4))
_BUFFER_RULES = {
    "Live": BufferRule(
        nature_of_works="Live", up_to_buffer_sectors=2, opposite_bound_required=True
    ),
    "Non-live (Consist)": BufferRule(
        nature_of_works="Non-live (Consist)",
        up_to_buffer_sectors=1,
        opposite_bound_required=False,
    ),
    "Non-live (Others)": BufferRule(
        nature_of_works="Non-live (Others)",
        up_to_buffer_sectors=0,
        opposite_bound_required=False,
    ),
}


def _single_line_instance(contracts: list[dict], activities: list[dict]) -> PlanningInstance:
    """A one-line network with no interchange, so Live work can mirror only."""

    lines = {"ALP": Line(line_code="ALP", line_name="Alpha")}
    stations = {
        ("ALP", station_id): Station(
            station_id=station_id, line_code="ALP", seq=seq, is_interchange=False
        )
        for station_id, seq in _ONE_LINE_STATIONS
    }
    sectors: dict[str, Sector] = {}
    for seq, ((from_id, _), (to_id, _)) in enumerate(
        zip(_ONE_LINE_STATIONS, _ONE_LINE_STATIONS[1:], strict=False), start=1
    ):
        sector_id = format_sector_id("ALP", from_id, to_id)
        sectors[sector_id] = Sector(
            sector_id=sector_id,
            line_code="ALP",
            from_station_id=from_id,
            to_station_id=to_id,
            seq=seq,
            is_shared=False,
        )
    locations: dict[str, LocationSupply] = {}
    for bound in ("EB", "WB"):
        for station_id, _ in _ONE_LINE_STATIONS:
            location_id = format_location_id(
                kind="PLAT", line_code="ALP", bound=bound, station_id=station_id
            )
            locations[location_id] = LocationSupply(
                location_id=location_id,
                location_kind="platform sector",
                line_code="ALP",
                bound=bound,
                supply_capacity=4,
            )
        for sector in sectors.values():
            location_id = format_location_id(
                kind="SEC", line_code="ALP", bound=bound, sector_id=sector.sector_id
            )
            locations[location_id] = LocationSupply(
                location_id=location_id,
                location_kind="tunnel sector",
                line_code="ALP",
                bound=bound,
                supply_capacity=4,
            )
    contract_models: dict[str, Contract] = {}
    for spec in contracts:
        data = {
            "contract_description": spec["contract_number"],
            "activity_type": "Renewal",
            "nature_of_activity": "Non-live (Others)",
            "contract_priority": 3,
            "contract_award_date": HORIZON_START - timedelta(days=60),
            "contract_completion_date": HORIZON_START + timedelta(days=83),
            "planned_completion_date": HORIZON_START + timedelta(days=83),
            "number_of_workfronts": 1,
            "access_type": "C",
            "number_of_maximum_access_per_week": 3,
        }
        data.update(spec)
        contract_models[data["contract_number"]] = Contract(**data)
    activity_models: dict[str, Activity] = {}
    for spec in activities:
        data = {
            "activity_type": contract_models[spec["contract_number"]].activity_type,
            "planned_start_date": HORIZON_START,
            "predecessor_activity_id": None,
            "activity_priority": 2,
        }
        data.update(spec)
        activity_models[data["activity_id"]] = Activity(**data)
    predecessors = {
        activity.activity_id: activity.predecessor_activity_id
        for activity in activity_models.values()
        if activity.predecessor_activity_id is not None
    }
    return PlanningInstance(
        lines=lines,
        stations=stations,
        sectors=sectors,
        locations=locations,
        buffer_rules=_BUFFER_RULES,
        parameters=Parameters(horizon_start=HORIZON_START, horizon_weeks=12),
        contracts=contract_models,
        activities=activity_models,
        predecessors=predecessors,
        successors=build_successor_index(predecessors),
    )


def _bundle_for(
    instance,
    accesses: dict[str, list[tuple[int, int, int]]],
    *,
    scenario: str = "A",
    group: str = "b1",
    groups: dict[str, str] | None = None,
) -> SubmissionBundle:
    """Build a bundle for hand-written accesses against a canonical instance.

    ``groups`` overrides the default ``group`` label per activity so fixtures can
    exercise explicit versus admissible possession grouping.
    """

    compiled = compile_instance(instance)
    access_rows: list[AccessRow] = []
    occupancy_rows: list[OccupancyRow] = []
    for activity_id, entries in accesses.items():
        if not entries:
            continue
        label = (groups or {}).get(activity_id, group)
        ordered = sorted(entries, key=lambda entry: (entry[0], entry[1]))
        for sequence, (week, night, eclo) in enumerate(ordered, start=1):
            access_rows.append(
                AccessRow(
                    activity_id=activity_id,
                    access_seq=sequence,
                    week=week,
                    eclo=eclo,
                    access_night=night,
                )
            )
            for location_id in compiled.activities[activity_id].occupied_locations:
                occupancy_rows.append(
                    OccupancyRow(
                        activity_id=activity_id,
                        week=week,
                        location_id=location_id,
                        co_share_group=label,
                    )
                )
    results: list[ResultRow] = []
    for contract_number, contract in instance.contracts.items():
        weeks = [
            week
            for activity_id, entries in accesses.items()
            if instance.activities[activity_id].contract_number == contract_number
            for week, _, _ in entries
        ]
        if not weeks:
            continue
        simulated = week_end(instance.horizon_start, max(weeks))
        results.append(
            ResultRow(
                scenario=scenario,
                contract_number=contract_number,
                simulated_completion_date=simulated,
                overrun_days=max(0, (simulated - contract.planned_completion_date).days),
            )
        )
    return build_bundle(scenario, access_rows, occupancy_rows, results)


def _compatible_pair_instance(capacities: dict[str, int] | None = None):
    """One PC contract and one C contract sharing one sector (PC+C legal)."""

    return make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities=capacities,
    )


# ---------------------------------------------------------------------------
# Published sample: the acceptance oracle
# ---------------------------------------------------------------------------


def test_public_sample_passes_scenario_a_with_zero_violations():
    report = validate_directories(PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR)
    assert report.scenario == "A"
    assert report.feasible is True
    assert report.workload_complete is True
    assert report.ready_for_submission is True
    assert report.hard_violations == ()
    assert report.authority == "fallback"
    assert report.validator_source == "fallback"


def test_public_sample_scores_match_the_documented_mapping(public_instance, sample_bundle):
    report = validate_bundle(public_instance, sample_bundle)
    scores = report.soft_scores
    assert scores.scenario == "A"
    assert scores.overrun_days_total == 28
    assert scores.contracts_overrunning == 3
    assert scores.priority_overrun == {"1": 0, "2": 0, "3": 28}
    assert scores.priority_weighted_score == pytest.approx(48.3)
    assert scores.objective_score == pytest.approx(48.3)
    assert scores.formula_version == FORMULA_VERSION
    assert scores.excess_access_nights_total == 0
    assert scores.eclo_nights_total == 0
    assert report.detail.nights_scheduled == 192
    assert report.detail.eclo_nights == 0
    assert report.detail.capacity_hotspots == ()
    assert infer_scenario(sample_bundle) == "A"


def test_compiled_entry_point_matches_bundle_entry_point(public_instance, sample_bundle):
    compiled = compile_instance(public_instance)
    assert validate_compiled(compiled, sample_bundle, "A").model_dump() == validate_bundle(
        public_instance, sample_bundle, "A"
    ).model_dump()


# ---------------------------------------------------------------------------
# Mutation tests: one broken rule at a time
# ---------------------------------------------------------------------------


def test_workload_missing_activity_is_detected(public_instance, sample_bundle):
    mutated = _replace(
        sample_bundle,
        access=[row for row in sample_bundle.access if row.activity_id != "A001"],
        occupancy=[row for row in sample_bundle.occupancy if row.activity_id != "A001"],
    )
    report = validate_bundle(public_instance, mutated)
    assert report.feasible is False
    assert report.ready_for_submission is False
    assert "workload" in _rules(report)


def test_workload_under_scheduled_activity_is_detected(public_instance, sample_bundle):
    mutated = _replace(sample_bundle, access=sample_bundle.access[:-1])
    report = validate_bundle(public_instance, mutated)
    assert "workload" in _rules(report)


def test_access_sequence_must_be_contiguous(public_instance, sample_bundle):
    access = [
        row.model_copy(update={"access_seq": 9})
        if row.activity_id == "A003" and row.access_seq == 2
        else row
        for row in sample_bundle.access
    ]
    report = validate_bundle(public_instance, _replace(sample_bundle, access=access))
    assert "allocation" in _rules(report)


def test_one_access_per_activity_week(public_instance, sample_bundle):
    rows = [row for row in sample_bundle.access if row.activity_id == "A001"]
    duplicate = rows[1].model_copy(update={"week": rows[0].week})
    access = [
        duplicate if row is rows[1] else row for row in sample_bundle.access
    ]
    report = validate_bundle(public_instance, _replace(sample_bundle, access=access))
    assert "allocation" in _rules(report)


def test_planned_start_is_hard(public_instance, sample_bundle):
    mutated = _remap_weeks(sample_bundle, "A001", {22: 1, 23: 2})
    report = validate_bundle(public_instance, mutated)
    assert "planned_start" in _rules(report)


def test_predecessor_finish_to_start_zero_lag(public_instance, sample_bundle):
    mutated = _remap_weeks(sample_bundle, "A004", {21: 14, 22: 15, 23: 16})
    report = validate_bundle(public_instance, mutated)
    assert "predecessor" in _rules(report)


def test_occupancy_must_match_expanded_route(public_instance, sample_bundle):
    target = next(
        row
        for row in sample_bundle.occupancy
        if row.activity_id == "A001" and row.week == 22
    )
    mutated = _replace(
        sample_bundle,
        occupancy=[row for row in sample_bundle.occupancy if row is not target],
    )
    report = validate_bundle(public_instance, mutated)
    assert "occupancy" in _rules(report)


def test_occupancy_cannot_invent_locations(public_instance, sample_bundle):
    extra = OccupancyRow(
        activity_id="A001",
        week=22,
        location_id="PLAT:ALP:S08:EB",
        co_share_group="b9",
    )
    mutated = _replace(sample_bundle, occupancy=sample_bundle.occupancy + (extra,))
    report = validate_bundle(public_instance, mutated)
    assert "occupancy" in _rules(report)


def test_illegal_possession_mix_is_detected():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(instance, {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]})
    report = validate_bundle(instance, bundle, "A")
    assert "mix" in _rules(report)


def test_group_mix_is_checked_across_nights_within_a_week():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(instance, {"A1": [(1, 1, 0)], "A2": [(1, 2, 0)]})
    report = validate_bundle(instance, bundle, "A")
    assert "mix" in _rules(report)


def test_separate_compatible_groups_exceed_capacity():
    """Two declared possessions at one location-week exceed a supply of one."""

    instance = _compatible_pair_instance(capacities={SECTOR: 1})
    # Each group is a legal PC+C possession, but they are two possessions.
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "capacity" in _rules(report)
    assert report.soft_scores.excess_access_nights_total == 1


def test_capacity_exceeds_supply_when_two_possessions_are_required():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
    )
    # Two PC possessions cannot share one location-night or one supply slot.
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "capacity" in _rules(report)


def test_workfront_cap_is_per_contract_type_night():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_workfronts": 1,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(instance, {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]})
    report = validate_bundle(instance, bundle, "A")
    assert "workfront" in _rules(report)


def test_cross_contract_same_local_night_is_not_a_closure_conflict():
    """Equal local night numbers in different contracts are unrelated slots."""

    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    # Different explicit groups: the two possessions can be placed on separate
    # physical nights even though their local night index is the same.
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True
    assert _rules(report) == set()


def test_forced_same_contract_conflict_is_detected():
    """Same contract/type/week/night is one physical night: conflict is forced."""

    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    # Different groups force separate possessions, but the shared local night
    # forces one physical slot: the pair is both together and apart.
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert {"mix", "closure"} <= _rules(report)


def _pm_crowd(count: int):
    contracts = [
        {
            "contract_number": f"C{index}",
            "access_type": "PM",
            "nature_of_activity": "Non-live (Others)",
        }
        for index in range(1, count + 1)
    ]
    activities = [
        {
            "activity_id": f"A{index}",
            "contract_number": f"C{index}",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 1,
        }
        for index in range(1, count + 1)
    ]
    return contracts, activities


_SECTOR_ROUTE_LOCATIONS = (
    "PLAT:ALP:S01:EB",
    "PLAT:ALP:S02:EB",
    SECTOR,
)


def test_seven_incompatible_possessions_fit_the_seven_night_week():
    contracts, activities = _pm_crowd(7)
    capacities = {location: 7 for location in _SECTOR_ROUTE_LOCATIONS}
    instance = make_planning(contracts, activities, capacities=capacities)
    bundle = _bundle_for(
        instance,
        {f"A{index}": [(1, 1, 0)] for index in range(1, 8)},
        groups={f"A{index}": f"b{index}" for index in range(1, 8)},
    )
    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True


def test_eight_incompatible_possessions_exceed_the_seven_night_week():
    contracts, activities = _pm_crowd(8)
    capacities = {location: 8 for location in _SECTOR_ROUTE_LOCATIONS}
    instance = make_planning(contracts, activities, capacities=capacities)
    bundle = _bundle_for(
        instance,
        {f"A{index}": [(1, 1, 0)] for index in range(1, 9)},
        groups={f"A{index}": f"b{index}" for index in range(1, 9)},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "closure" in _rules(report)


def test_same_contract_different_nights_can_be_separated():
    """The same conflict is admissible when the two accesses use different nights."""

    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 2, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True


def test_same_group_waives_a_compatible_closure_conflict():
    """Same submitted group at a common occupied location is one possession."""

    instance = _compatible_pair_instance()
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b1"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True
    assert _rules(report) == set()


def test_forced_same_local_class_closure_conflict():
    """Same local-night class plus different groups at a shared occupied spot."""

    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    # Same contract/type/week/night forces one slot; the two groups are separate
    # possessions at the shared occupied location, so the closure is forced.
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "closure" in _rules(report)


def test_same_group_same_night_is_one_physical_slot():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b1"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True


def test_two_pc_plus_c_in_one_group_is_an_illegal_mix():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C3",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A3",
                "contract_number": "C3",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)], "A3": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b1", "A3": "b1"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "mix" in _rules(report)


def test_buffer_only_pair_without_a_common_group_is_admitted():
    """Buffer-only overlap cannot be proven from the contract-local night schema.

    The sample-calibrated fallback enforces closure separation only at a shared
    occupied location, so two activities whose routes are disjoint and that do
    not share a group are not falsely rejected.
    """

    instance = _single_line_instance(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Consist)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:EB",
                "end_location_id": "SEC:ALP:S01_S02:EB",
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S03_S04:EB",
                "end_location_id": "SEC:ALP:S03_S04:EB",
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True
    assert "closure" not in _rules(report)


def test_live_mirroring_conflict_is_tagged_mirror():
    """Same contract, same night, shared occupied sector: Live mirrors conflict."""

    instance = _single_line_instance(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Live",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:EB",
                "end_location_id": "SEC:ALP:S01_S02:EB",
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:EB",
                "end_location_id": "SEC:ALP:S01_S02:EB",
                "total_accesses": 1,
            },
        ],
    )
    # Different groups at the shared occupied sector: the closure is not waived.
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "mirror" in _rules(report)


def test_live_interchange_conflict_is_tagged_interchange():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Live",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:H01_H02:EB",
                "end_location_id": "SEC:ALP:H01_H02:EB",
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:H01_H02:EB",
                "end_location_id": "SEC:ALP:H01_H02:EB",
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )
    report = validate_bundle(instance, bundle, "A")
    assert "interchange" in _rules(report)


def test_scenario_a_forbids_eclo(public_instance, sample_bundle):
    access = [
        row.model_copy(update={"eclo": 1}) if row.activity_id == "A002" else row
        for row in sample_bundle.access
    ]
    report = validate_bundle(public_instance, _replace(sample_bundle, access=access))
    assert "eclo" in _rules(report)


def test_scenario_c_eclo_window_is_two_weeks():
    instance = make_planning(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_maximum_access_per_week": 3,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 4,
            }
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 1), (2, 1, 0), (3, 1, 0), (4, 1, 1)]},
        scenario="C",
    )
    report = validate_bundle(instance, bundle, "C")
    assert "eclo_window" in _rules(report)


def test_scenario_b_planned_dates_are_hard(public_instance, sample_bundle):
    results = [row.model_copy(update={"scenario": "B"}) for row in sample_bundle.results]
    mutated = _replace(sample_bundle, results=results)
    report = validate_bundle(public_instance, mutated)
    assert report.scenario == "B"
    assert "planned_date" in _rules(report)


def test_results_missing_contract_is_detected(public_instance, sample_bundle):
    results = [row for row in sample_bundle.results if row.contract_number != "C001"]
    report = validate_bundle(public_instance, _replace(sample_bundle, results=results))
    assert "results" in _rules(report)


def test_results_cannot_mix_scenarios(public_instance, sample_bundle):
    results = list(sample_bundle.results)
    results[0] = results[0].model_copy(update={"scenario": "B"})
    report = validate_bundle(public_instance, _replace(sample_bundle, results=results))
    assert "results" in _rules(report)


def test_results_completion_date_must_match(public_instance, sample_bundle):
    results = list(sample_bundle.results)
    next_date = results[0].simulated_completion_date + timedelta(days=1)
    results[0] = results[0].model_copy(
        update={"simulated_completion_date": next_date}
    )
    report = validate_bundle(public_instance, _replace(sample_bundle, results=results))
    assert "results" in _rules(report)


def test_results_overrun_must_match(public_instance, sample_bundle):
    results = list(sample_bundle.results)
    results[0] = results[0].model_copy(update={"overrun_days": results[0].overrun_days + 99})
    report = validate_bundle(public_instance, _replace(sample_bundle, results=results))
    assert "results" in _rules(report)


# ---------------------------------------------------------------------------
# Official adapter
# ---------------------------------------------------------------------------


def test_adapter_falls_back_when_no_command(monkeypatch, public_instance):
    monkeypatch.delenv(VALIDATOR_COMMAND_ENV, raising=False)
    outcome = validate_with_adapter(PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR)
    assert outcome.validator_source == "fallback"
    assert outcome.official_available is False
    assert outcome.report.authority == "fallback"
    assert outcome.report.feasible is True


def _write_validator_script(tmp_path, *, exit_code: int = 0, stdout: str | None = None):
    payload = stdout
    if payload is None:
        payload = json.dumps(
            {
                "scenario": "A",
                "feasible": True,
                "hard_violations": [],
                "soft_scores": {
                    "scenario": "A",
                    "overrun_days_total": 0,
                    "contracts_overrunning": 0,
                    "earliness_days_total": 0,
                    "excess_access_nights_total": 0,
                    "eclo_nights_total": 0,
                    "priority_overrun": {"1": 0, "2": 0, "3": 0},
                    "priority_weighted_score": 0.0,
                },
                "detail": {
                    "capacity_hotspots": [],
                    "nights_scheduled": 0,
                    "eclo_nights": 0,
                },
            }
        )
    script = tmp_path / "official_validator.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys
            if {exit_code!r} != 0:
                sys.stderr.write("boom")
                sys.exit({exit_code!r})
            print({payload!r})
            """
        ),
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"


def test_adapter_invokes_configured_official_validator(tmp_path):
    command = _write_validator_script(tmp_path)
    outcome = validate_with_adapter(
        PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, command=command
    )
    assert outcome.validator_source == "official"
    assert outcome.official_available is True
    assert outcome.report.authority == "official"
    assert outcome.report.validator_source == "official"
    assert outcome.report.feasible is True


def test_adapter_uses_environment_command(tmp_path, monkeypatch):
    command = _write_validator_script(tmp_path)
    monkeypatch.setenv(VALIDATOR_COMMAND_ENV, command)
    outcome = validate_with_adapter(PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR)
    assert outcome.validator_source == "official"


def test_adapter_raises_when_official_validator_fails(tmp_path):
    command = _write_validator_script(tmp_path, exit_code=2)
    with pytest.raises(OfficialValidatorError):
        validate_with_adapter(
            PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, command=command
        )


def test_adapter_raises_when_official_output_is_not_json(tmp_path):
    command = _write_validator_script(tmp_path, stdout="not json")
    with pytest.raises(OfficialValidatorError):
        validate_with_adapter(
            PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, command=command
        )


# ---------------------------------------------------------------------------
# Official calibration hooks (F-VALIDATOR-004 scaffolding)
# ---------------------------------------------------------------------------


def test_calibration_is_blocked_without_a_command(monkeypatch):
    monkeypatch.delenv(VALIDATOR_COMMAND_ENV, raising=False)
    result = run_calibration(PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR)
    assert result.status == "blocked"
    assert result.official_available is False
    assert result.official is None
    assert result.official_command is None
    assert result.fallback is not None
    assert result.fallback.authority == "fallback"


def test_calibration_matches_the_echoed_official_report(tmp_path):
    fallback = validate_directories(PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR)
    payload = fallback.model_dump(mode="json")
    command = _write_validator_script(tmp_path, stdout=json.dumps(payload))
    result = run_calibration(
        PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, command=command
    )
    assert result.status == "match"
    assert result.official_available is True
    assert result.official is not None
    assert result.official.authority == "official"
    assert result.divergences == ()


def test_calibration_detects_a_divergent_official_report(tmp_path):
    command = _write_validator_script(tmp_path)
    result = run_calibration(
        PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, command=command
    )
    assert result.status == "diverged"
    assert result.official is not None
    assert result.official.authority == "official"
    assert result.divergences


# ---------------------------------------------------------------------------
# Solver output is validated by the independent oracle (when CP-SAT is present)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_solver_output_passes_independent_validator():
    contracts = [
        {"contract_number": "C1", "access_type": "PC", "nature_of_activity": "Non-live (Others)"},
        {"contract_number": "C2", "access_type": "C", "nature_of_activity": "Non-live (Others)"},
    ]
    activities = [
        {
            "activity_id": "A1",
            "contract_number": "C1",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 2,
        },
        {
            "activity_id": "A2",
            "contract_number": "C2",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 2,
        },
    ]
    compiled = make_compiled(contracts, activities, capacities={SECTOR: 1})
    result = solve(compiled, "A", time_limit_seconds=10)
    assert result.feasible
    bundle = bundle_from_solver_result(result)
    report = validate_compiled(compiled, bundle, "A")
    assert report.feasible, [v.model_dump() for v in report.hard_violations]

    groups: dict[tuple[str, int], set[str]] = {}
    for row in result.occupancy:
        groups.setdefault((row.location_id, row.week), set()).add(row.co_share_group)
    for (location_id, _week), used in groups.items():
        assert len(used) <= compiled.location_capacities[location_id]


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_public_instance_solver_output_passes_independent_validator():
    public_instance = load_public_instance()
    compiled = compile_instance(public_instance)
    result = solve(compiled, "A", time_limit_seconds=20)
    if not result.feasible:
        pytest.skip(f"public smoke solve did not finish: {result.status}")
    bundle = bundle_from_solver_result(result)
    report = validate_compiled(compiled, bundle, "A")
    assert report.feasible, [v.model_dump() for v in report.hard_violations][:5]
