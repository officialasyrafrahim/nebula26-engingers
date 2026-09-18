"""Scenario-driven CP-SAT engine for the rail access solver.

The engine builds one model per scenario, solves it with deterministic search
settings, and extracts the published ``SolverResult`` contract. There is no
legacy maintenance fallback: if the native solver cannot import, a clear
:class:`OrToolsUnavailableError` is raised; if the model is infeasible, the
result carries structured reasons instead.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.rail.compiled import CompiledInstance
from app.domain.rail.instance_model import planned_start_week
from app.modules.compiler.policy import ScenarioPolicy, get_policy
from app.modules.solver.constraints import (
    add_capacity_constraints,
    add_caps_constraints,
    add_completion_constraints,
    add_eclo_constraints,
    add_linking_constraints,
    add_possession_constraints,
    add_time_constraints,
)
from app.modules.solver.model import (
    DEFAULT_HORIZON_EXTENSION_WEEKS,
    DEFAULT_SEED,
    DEFAULT_TIME_LIMIT_SECONDS,
    load_cp_model,
)
from app.modules.solver.objectives import build_objective, contract_weight
from app.modules.solver.results import (
    AccessPlacement,
    ContractResult,
    OccupancyPlacement,
    SolverResult,
    week_end,
)
from app.modules.solver.variables import SolverVariables, build_variables

Scenario = Literal["A", "B", "C"]


class RailPlanRequest(BaseModel):
    """Solver-boundary request matching the architecture blueprint."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    instance: CompiledInstance
    scenario: Scenario
    time_limit_seconds: float = Field(default=DEFAULT_TIME_LIMIT_SECONDS, gt=0)
    seed: int = DEFAULT_SEED
    horizon_extension_weeks: int = Field(default=DEFAULT_HORIZON_EXTENSION_WEEKS, ge=0)


def resolve_total_weeks(compiled: CompiledInstance, extension_weeks: int) -> int:
    """Nominal horizon plus extension, widened to cover planned dates."""

    instance = compiled.instance
    total = instance.horizon_weeks + extension_weeks
    for activity in instance.activities.values():
        total = max(
            total, planned_start_week(instance.horizon_start, activity.planned_start_date)
        )
    for contract in instance.contracts.values():
        planned_week = planned_start_week(
            instance.horizon_start, contract.planned_completion_date
        )
        total = max(total, planned_week)
    return max(total, 1)


def solve(
    compiled: CompiledInstance,
    scenario: Scenario,
    *,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    seed: int = DEFAULT_SEED,
    horizon_extension_weeks: int = DEFAULT_HORIZON_EXTENSION_WEEKS,
) -> SolverResult:
    """Solve one scenario for a compiled instance."""

    policy = get_policy(scenario)
    return _solve(compiled, policy, time_limit_seconds, seed, horizon_extension_weeks)


def solve_request(request: RailPlanRequest) -> SolverResult:
    """Solve from a :class:`RailPlanRequest`."""

    return solve(
        request.instance,
        request.scenario,
        time_limit_seconds=request.time_limit_seconds,
        seed=request.seed,
        horizon_extension_weeks=request.horizon_extension_weeks,
    )


def _solve(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    time_limit_seconds: float,
    seed: int,
    horizon_extension_weeks: int,
) -> SolverResult:
    cp = load_cp_model()
    total_weeks = resolve_total_weeks(compiled, horizon_extension_weeks)
    model = cp.CpModel()
    variables = build_variables(model, compiled, policy, total_weeks)

    add_linking_constraints(model, compiled, variables)
    add_time_constraints(model, compiled, variables)
    add_caps_constraints(model, compiled, variables)
    add_possession_constraints(model, compiled, variables)
    add_capacity_constraints(model, compiled, variables, policy)
    add_completion_constraints(model, compiled, variables, policy)
    add_eclo_constraints(model, compiled, variables, policy)
    build_objective(model, compiled, variables, policy)

    solver = cp.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp.OPTIMAL, cp.FEASIBLE):
        return SolverResult(
            feasible=False,
            scenario=policy.scenario,
            status=status_name,
            horizon_weeks_used=0,
            objective_breakdown={"scenario": policy.scenario},
            infeasibility_reasons=_infeasibility_reasons(
                compiled, policy, total_weeks, status_name
            ),
        )

    return _extract_result(compiled, policy, variables, solver, total_weeks, status_name)


def _extract_result(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    variables: SolverVariables,
    solver: Any,
    total_weeks: int,
    status_name: str,
) -> SolverResult:
    access_rows: list[AccessPlacement] = []
    occupancy_rows: list[OccupancyPlacement] = []
    access_weeks: dict[str, list[tuple[int, int, bool]]] = {}

    for activity_id in variables.activity_order:
        activity = compiled.activities[activity_id]
        accesses: list[tuple[int, int, bool]] = []
        for week in variables.activity_weeks[activity_id]:
            for night in variables.activity_nights[activity_id]:
                for eclo in variables.eclo_values:
                    key = (activity_id, week, night, eclo)
                    if key in variables.x and solver.Value(variables.x[key]) > 0.5:
                        accesses.append((week, night, bool(eclo)))
        accesses.sort(key=lambda item: (item[0], item[1]))
        access_weeks[activity_id] = accesses
        for sequence, (week, night, eclo) in enumerate(accesses, start=1):
            access_rows.append(
                AccessPlacement(
                    activity_id=activity_id,
                    access_seq=sequence,
                    week=week,
                    eclo=eclo,
                    access_night=night,
                )
            )
            for location_id in dict.fromkeys(activity.occupied_locations):
                occupancy_rows.append(
                    OccupancyPlacement(
                        activity_id=activity_id,
                        week=week,
                        location_id=location_id,
                        co_share_group=f"b{night}",
                    )
                )

    occupancy_rows.sort(
        key=lambda row: (row.activity_id, row.week, row.co_share_group, row.location_id)
    )

    contract_results = _contract_results(compiled, access_weeks)
    breakdown = _objective_breakdown(
        compiled, policy, variables, solver, access_rows, occupancy_rows, contract_results
    )
    horizon_used = max((row.week for row in access_rows), default=0)

    return SolverResult(
        feasible=True,
        scenario=policy.scenario,
        status=status_name,
        horizon_weeks_used=horizon_used,
        access=tuple(access_rows),
        occupancy=tuple(occupancy_rows),
        contract_results=tuple(contract_results),
        contract_completion={
            result.contract_number: result.simulated_completion_date
            for result in contract_results
        },
        objective_breakdown=breakdown,
        binding_reasons=_binding_reasons(compiled, variables, access_weeks, policy),
    )


def _contract_results(
    compiled: CompiledInstance,
    access_weeks: dict[str, list[tuple[int, int, bool]]],
) -> list[ContractResult]:
    results: list[ContractResult] = []
    horizon_start = compiled.instance.horizon_start
    for contract_number, contract in sorted(compiled.instance.contracts.items()):
        activities = compiled.activities_for_contract(contract_number)
        if not activities:
            continue
        weeks = [
            week
            for activity in activities
            for week, _, _ in access_weeks.get(activity.activity_id, [])
        ]
        last_week = max(weeks, default=0)
        if last_week == 0:
            continue
        simulated = week_end(horizon_start, last_week)
        overrun = max(0, (simulated - contract.planned_completion_date).days)
        results.append(
            ContractResult(
                contract_number=contract_number,
                contract_priority=contract.contract_priority,
                planned_completion_date=contract.planned_completion_date,
                simulated_completion_date=simulated,
                overrun_days=overrun,
                last_week=last_week,
            )
        )
    results.sort(key=lambda result: result.contract_number)
    return results


def _objective_breakdown(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    variables: SolverVariables,
    solver: Any,
    access_rows: list[AccessPlacement],
    occupancy_rows: list[OccupancyPlacement],
    contract_results: list[ContractResult],
) -> dict[str, Any]:
    groups: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in occupancy_rows:
        groups[(row.location_id, row.week)].add(row.co_share_group)

    excess_total = 0
    hotspots: list[dict[str, Any]] = []
    for (location_id, week), used_groups in sorted(groups.items()):
        capacity = compiled.location_capacities.get(location_id, 0)
        used = len(used_groups)
        excess = max(0, used - capacity)
        excess_total += excess
        if used >= capacity:
            hotspots.append(
                {
                    "location_id": location_id,
                    "week": week,
                    "used": used,
                    "capacity": capacity,
                    "excess": excess,
                }
            )

    eclo_total = sum(1 for row in access_rows if row.eclo)
    overrun_days_total = sum(result.overrun_days for result in contract_results)
    priority_overrun: dict[str, int] = defaultdict(int)
    priority_weighted = 0.0
    for result in contract_results:
        priority_overrun[str(result.contract_priority)] += result.overrun_days
        priority_weighted += (
            contract_weight(compiled, result.contract_number) * result.overrun_days
        )

    excess_cost = policy.excess_access_nights_scored * 7 * excess_total
    eclo_cost = policy.eclo_scored * 5 * eclo_total
    if policy.scenario == "B":
        score = excess_cost + eclo_cost
    else:
        score = priority_weighted + excess_cost + eclo_cost

    return {
        "scenario": policy.scenario,
        "overrun_days_total": overrun_days_total,
        "contracts_overrunning": sum(
            1 for result in contract_results if result.overrun_days > 0
        ),
        "priority_overrun": {
            str(tier): priority_overrun.get(str(tier), 0) for tier in (1, 2, 3)
        },
        "priority_weighted_score": priority_weighted,
        "excess_access_nights_total": excess_total,
        "eclo_nights_total": eclo_total,
        "access_nights_total": len(access_rows),
        "nights_scheduled": len(access_rows),
        "overshoot_units": int(solver.Value(variables.overshoot)),
        "solver_objective": solver.ObjectiveValue(),
        "score": score,
        "capacity_hotspots": hotspots,
    }


def _binding_reasons(
    compiled: CompiledInstance,
    variables: SolverVariables,
    access_weeks: dict[str, list[tuple[int, int, bool]]],
    policy: ScenarioPolicy,
) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    horizon = compiled.instance.horizon_weeks
    access_index = {
        (activity_id, week, night): True
        for activity_id, accesses in access_weeks.items()
        for week, night, _ in accesses
    }
    for activity_id in variables.activity_order:
        accesses = access_weeks.get(activity_id, [])
        if not accesses:
            continue
        activity = compiled.activities[activity_id]
        first_week = accesses[0][0]
        codes: set[str] = {"PLANNED_START"}
        if first_week > horizon:
            codes.add("HORIZON_EXTENDED")
        if activity.predecessor_activity_id is not None:
            predecessor_accesses = access_weeks.get(activity.predecessor_activity_id, [])
            if predecessor_accesses and first_week == predecessor_accesses[-1][0] + 1:
                codes.add("PREDECESSOR")
        if any(eclo for _, _, eclo in accesses):
            codes.add("ECLO")
        if _shares_possession(compiled, activity_id, accesses, access_index):
            codes.add("CO_SHARE_PACKED")
        reasons[activity_id] = sorted(codes)
    return reasons


def _shares_possession(
    compiled: CompiledInstance,
    activity_id: str,
    accesses: list[tuple[int, int, bool]],
    access_index: dict[tuple[str, int, int], bool],
) -> bool:
    locations = set(compiled.activities[activity_id].occupied_locations)
    for other_id, other in compiled.activities.items():
        if other_id == activity_id:
            continue
        if not locations & set(other.occupied_locations):
            continue
        for week, night, _ in accesses:
            if access_index.get((other_id, week, night)):
                return True
    return False


def _infeasibility_reasons(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    total_weeks: int,
    status_name: str,
) -> list[str]:
    reasons: list[str] = []
    horizon_start = compiled.instance.horizon_start
    for activity_id in sorted(compiled.activities):
        activity = compiled.activities[activity_id]
        if activity.planned_start_week > total_weeks:
            reasons.append(
                f"activity {activity_id} planned start week {activity.planned_start_week} "
                f"is beyond the {total_weeks}-week horizon"
            )
    if policy.planned_completion_hard:
        for contract_number, contract in sorted(compiled.instance.contracts.items()):
            completion_week = planned_start_week(
                horizon_start, contract.planned_completion_date
            )
            for activity in compiled.activities_for_contract(contract_number):
                if activity.planned_start_week > completion_week:
                    reasons.append(
                        f"activity {activity.activity_id} cannot finish before planned "
                        f"completion week {completion_week} of contract {contract_number}"
                    )
                    continue
                weeks_available = completion_week - activity.planned_start_week + 1
                # Each week yields 3 half-units under ECLO, otherwise 2.
                if policy.eclo_allowed:
                    required_weeks = (2 * activity.total_accesses + 2) // 3
                else:
                    required_weeks = activity.total_accesses
                if required_weeks > weeks_available:
                    reasons.append(
                        f"activity {activity.activity_id} needs {required_weeks} weeks "
                        f"of access but only {weeks_available} are available before "
                        f"contract {contract_number}'s planned completion"
                    )
    if not reasons:
        reasons.append(
            f"CP-SAT returned {status_name}: the hard {policy.scenario}-scenario "
            "constraints cannot be satisfied within the current horizon"
        )
    return reasons


__all__ = [
    "RailPlanRequest",
    "Scenario",
    "resolve_total_weeks",
    "solve",
    "solve_request",
]
