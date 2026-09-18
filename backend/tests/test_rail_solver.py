"""Rail access solver constraints and determinism (AT-03..AT-08).

The tests build tiny synthetic compiled instances directly (no CSV parsing and
no database) so each CP-SAT model is solved in well under a second. When the
native OR-Tools runtime is genuinely unimportable the whole module skips; it
never falls back to a legacy maintenance solver.
"""

from __future__ import annotations

from datetime import date, timedelta

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
from app.modules.solver import (
    RailPlanRequest,
    SolverResult,
    cp_sat_available,
    solve,
    solve_request,
)

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

HORIZON_START = date(2027, 1, 4)
LINE_STATIONS = {
    "ALP": (("S01", 1), ("S02", 2), ("H01", 3), ("H02", 4), ("S03", 5)),
    "BET": (("S11", 1), ("S12", 2), ("H01", 3), ("H02", 4), ("S13", 5)),
}
BUFFER_RULES = {
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


def _network(capacities: dict[str, int]):
    lines = {
        "ALP": Line(line_code="ALP", line_name="Alpha"),
        "BET": Line(line_code="BET", line_name="Beta"),
    }
    stations: dict[tuple[str, str], Station] = {}
    sectors: dict[str, Sector] = {}
    locations: dict[str, LocationSupply] = {}
    for line, spec in LINE_STATIONS.items():
        for station_id, seq in spec:
            stations[(line, station_id)] = Station(
                station_id=station_id,
                line_code=line,
                seq=seq,
                is_interchange=station_id in ("H01", "H02"),
            )
        for seq, (frm, to) in enumerate(
            ((spec[i][0], spec[i + 1][0]) for i in range(len(spec) - 1)), start=1
        ):
            sector_id = format_sector_id(line, frm, to)
            sectors[sector_id] = Sector(
                sector_id=sector_id,
                line_code=line,
                from_station_id=frm,
                to_station_id=to,
                seq=seq,
                is_shared=False,
            )
    for line, spec in LINE_STATIONS.items():
        for bound in ("EB", "WB"):
            for station_id, _ in spec:
                location_id = format_location_id(
                    kind="PLAT", line_code=line, bound=bound, station_id=station_id
                )
                locations[location_id] = LocationSupply(
                    location_id=location_id,
                    location_kind="platform sector",
                    line_code=line,
                    bound=bound,
                    supply_capacity=capacities.get(location_id, 4),
                )
            for sector in sectors.values():
                if sector.line_code != line:
                    continue
                location_id = format_location_id(
                    kind="SEC", line_code=line, bound=bound, sector_id=sector.sector_id
                )
                locations[location_id] = LocationSupply(
                    location_id=location_id,
                    location_kind="tunnel sector",
                    line_code=line,
                    bound=bound,
                    supply_capacity=capacities.get(location_id, 4),
                )
    return lines, stations, sectors, locations


def make_planning(
    contracts: list[dict],
    activities: list[dict],
    *,
    capacities: dict[str, int] | None = None,
    horizon_weeks: int = 12,
) -> PlanningInstance:
    capacities = capacities or {}
    lines, stations, sectors, locations = _network(capacities)
    horizon_end = HORIZON_START + timedelta(days=7 * horizon_weeks - 1)
    contract_models: dict[str, Contract] = {}
    for spec in contracts:
        data = {
            "contract_description": spec["contract_number"],
            "activity_type": "Renewal",
            "nature_of_activity": "Non-live (Others)",
            "contract_priority": 3,
            "contract_award_date": HORIZON_START - timedelta(days=60),
            "contract_completion_date": horizon_end,
            "planned_completion_date": horizon_end,
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
        buffer_rules=BUFFER_RULES,
        parameters=Parameters(horizon_start=HORIZON_START, horizon_weeks=horizon_weeks),
        contracts=contract_models,
        activities=activity_models,
        predecessors=predecessors,
        successors=build_successor_index(predecessors),
    )


def make_compiled(contracts: list[dict], activities: list[dict], **kwargs):
    return compile_instance(make_planning(contracts, activities, **kwargs))


def activity_access(result: SolverResult, activity_id: str) -> list[tuple[int, int, bool]]:
    return sorted(
        (row.week, row.access_night, row.eclo)
        for row in result.access
        if row.activity_id == activity_id
    )


def location_positions(result: SolverResult) -> dict[tuple[str, int], int]:
    grouped: dict[tuple[str, int], set[str]] = {}
    for row in result.occupancy:
        grouped.setdefault((row.location_id, row.week), set()).add(row.co_share_group)
    return {key: len(groups) for key, groups in grouped.items()}


def _standard_contracts() -> list[dict]:
    return [
        {"contract_number": "C1", "access_type": "C", "nature_of_activity": "Non-live (Others)"}
    ]


def _single_sector() -> dict:
    return {
        "start_location_id": "SEC:ALP:S01_S02:EB",
        "end_location_id": "SEC:ALP:S01_S02:EB",
    }


def test_workload_and_planned_start():
    compiled = make_compiled(
        _standard_contracts(),
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 3,
                "planned_start_date": HORIZON_START + timedelta(days=14),
            }
        ],
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    assert result.feasible
    accesses = activity_access(result, "A1")
    assert len(accesses) == 3
    assert min(week for week, _, _ in accesses) >= 3
    assert sum(3 if eclo else 2 for _, _, eclo in accesses) >= 6


def test_predecessor_finish_to_start_zero_lag():
    compiled = make_compiled(
        _standard_contracts(),
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
                "start_location_id": "SEC:ALP:H01_H02:EB",
                "end_location_id": "SEC:ALP:H01_H02:EB",
                "total_accesses": 1,
                "predecessor_activity_id": "A1",
            },
        ],
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    first = activity_access(result, "A1")
    second = activity_access(result, "A2")
    assert result.feasible
    assert max(week for week, _, _ in first) < min(week for week, _, _ in second)


def test_incompatible_closure_overlap_never_shares_a_night():
    contracts = [
        {
            "contract_number": "C1",
            "access_type": "PC",
            "nature_of_activity": "Non-live (Consist)",
        },
        {
            "contract_number": "C2",
            "access_type": "PC",
            "nature_of_activity": "Non-live (Consist)",
        },
    ]
    compiled = make_compiled(
        contracts,
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
                "contract_number": "C2",
                "start_location_id": "SEC:ALP:H01_H02:EB",
                "end_location_id": "SEC:ALP:H01_H02:EB",
                "total_accesses": 1,
            },
        ],
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    nights_a = {(week, night) for week, night, _ in activity_access(result, "A1")}
    nights_b = {(week, night) for week, night, _ in activity_access(result, "A2")}
    assert result.feasible
    assert nights_a.isdisjoint(nights_b)


def test_compatible_activities_co_share_a_single_possession():
    contracts = [
        {"contract_number": "C1", "access_type": "PC", "nature_of_activity": "Non-live (Others)"},
        {"contract_number": "C2", "access_type": "C", "nature_of_activity": "Non-live (Others)"},
    ]
    compiled = make_compiled(
        contracts,
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
        capacities={"SEC:ALP:S01_S02:EB": 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    accesses = activity_access(result, "A1")
    assert accesses == activity_access(result, "A2")
    groups = {row.co_share_group for row in result.occupancy}
    assert groups == {f"b{accesses[0][1]}"}


def test_pm_and_coworker_cannot_share_a_location_night():
    contracts = [
        {"contract_number": "C1", "access_type": "PM", "nature_of_activity": "Non-live (Others)"},
        {"contract_number": "C2", "access_type": "C", "nature_of_activity": "Non-live (Others)"},
    ]
    compiled = make_compiled(
        contracts,
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
        capacities={"SEC:ALP:S01_S02:EB": 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible is False
    assert result.infeasibility_reasons


def test_weekly_night_cap_and_workfront():
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_maximum_access_per_week": 3,
                "number_of_workfronts": 1,
            }
        ],
        [
            {
                "activity_id": f"A{index}",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            }
            for index in range(1, 4)
        ],
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    nights = {
        (row.week, row.access_night)
        for row in result.access
    }
    assert len(nights) == 3
    assert len({night for _, night in nights}) <= 3


def test_deterministic_output_for_fixed_seed():
    compiled = make_compiled(
        _standard_contracts(),
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 2,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:H01_H02:EB",
                "end_location_id": "SEC:ALP:H01_H02:EB",
                "total_accesses": 2,
            },
        ],
    )
    first = solve(compiled, "C", seed=42, time_limit_seconds=10)
    second = solve(compiled, "C", seed=42, time_limit_seconds=10)

    assert first.feasible and second.feasible
    assert first.access == second.access
    assert first.occupancy == second.occupancy
    assert first.objective_breakdown["score"] == second.objective_breakdown["score"]


def test_plan_request_boundary_contract():
    compiled = make_compiled(
        _standard_contracts(),
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            }
        ],
    )
    request = RailPlanRequest(
        instance=compiled, scenario="A", time_limit_seconds=10, seed=7
    )
    result = solve_request(request)

    assert result.feasible
    assert result.scenario == "A"
    assert result.contract_completion
    assert all(row.co_share_group.startswith("b") for row in result.occupancy)
