"""Scenario-driven CP-SAT engine for the rail access solver.

The engine builds one model per scenario, solves it with deterministic search
settings, and extracts the published ``SolverResult`` contract. There is no
legacy maintenance fallback: if the native solver cannot import, a clear
:class:`OrToolsUnavailableError` is raised; if the model is infeasible, the
result carries structured reasons instead.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.rail.compiled import CompiledInstance
from app.domain.rail.instance_model import planned_start_week
from app.modules.compiler.mixes import legal_access_mix
from app.modules.compiler.policy import ScenarioPolicy, get_policy
from app.modules.solver import reasons
from app.modules.solver.constraints import (
    add_capacity_constraints,
    add_caps_constraints,
    add_completion_constraints,
    add_eclo_constraints,
    add_linking_constraints,
    add_possession_constraints,
    add_time_constraints,
)
from app.modules.solver.greedy import GreedySolution, build_greedy_solution
from app.modules.solver.model import (
    DEFAULT_HORIZON_EXTENSION_WEEKS,
    DEFAULT_SEED,
    DEFAULT_TIME_LIMIT_SECONDS,
    load_cp_model,
)
from app.modules.solver.objectives import activity_weight, build_objective
from app.modules.solver.possession import truly_co_sharable
from app.modules.solver.results import (
    AccessPlacement,
    ContractResult,
    OccupancyPlacement,
    SolverResult,
    week_end,
)
from app.modules.solver.variables import SolverVariables, build_variables
from app.modules.validator.witness import check_physical_witness

Scenario = Literal["A", "B", "C"]

# Reason codes a genuine earlier-week blockage can earn. POSSESSION_MIX is
# deliberately absent because it may only be claimed by work that shares a
# co_share_group, which a rejected-week mix failure does not establish.
_DISPLACEMENT_REASON_CODES = frozenset(
    {
        reasons.CAPACITY,
        reasons.WEEKLY_CAP,
        reasons.WORKFRONT,
        reasons.BUFFER_CLOSURE,
        reasons.LIVE_MIRROR,
        reasons.INTERCHANGE,
    }
)


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


def completion_bound(compiled: CompiledInstance) -> int:
    """A safe finite week bound for a flexible-date schedule.

    With flexible dates a complete roster always fits by scheduling at most one
    access per week in dependency order: no capacity, closure or workfront
    conflict can arise across distinct weeks, and ECLO is optional. The bound is
    therefore the latest planned start plus the total standard workload. It is
    deliberately loose; the time budget and the growth search normally stop far
    earlier.
    """

    total_accesses = sum(
        activity.total_accesses for activity in compiled.activities.values()
    )
    latest_start = max(
        (activity.planned_start_week for activity in compiled.activities.values()),
        default=1,
    )
    return max(1, latest_start + total_accesses)


def _solve(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    time_limit_seconds: float,
    seed: int,
    horizon_extension_weeks: int,
) -> SolverResult:
    """Solve one scenario, growing the horizon within the time budget.

    The first attempt uses the configured horizon (nominal weeks plus the
    extension). When that cannot host the whole workload, the solver retries
    with a larger horizon until either a complete incumbent is found, a safe
    completion bound is reached, or the overall time budget is spent.

    Flexible-date scenarios (A/C) grow to :func:`completion_bound`. An
    ``INFEASIBLE`` result is never a proof for them, so it is reported as
    ``UNKNOWN``. Scenario B keeps its hard planned completion, so growing cannot
    help and a proven infeasibility is returned immediately.

    A caller that sets ``horizon_extension_weeks`` to zero has explicitly fixed
    the horizon, so adaptive growth is disabled for that call. Congestion is
    still not turned into proven infeasibility for a flexible-date scenario.

    A timed-out (``UNKNOWN``) attempt does not abandon the remaining budget: as
    long as time and the bound allow, the horizon is expanded and solved again.
    """

    cp = load_cp_model()
    initial_weeks = resolve_total_weeks(compiled, horizon_extension_weeks)
    if horizon_extension_weeks <= 0:
        last = _attempt(cp, compiled, policy, initial_weeks, time_limit_seconds, seed)
        return _finalize_flexible(last, policy, initial_weeks)

    growth_step = max(1, horizon_extension_weeks)
    if policy.planned_completion_hard:
        bound_weeks = initial_weeks
    else:
        bound_weeks = max(initial_weeks, completion_bound(compiled))
    deadline = time.monotonic() + float(time_limit_seconds)

    horizon = initial_weeks
    last: SolverResult | None = None
    while True:
        remaining = deadline - time.monotonic()
        if last is not None and remaining <= 0.01:
            break
        budget = _attempt_budget(time_limit_seconds, remaining)
        last = _attempt(cp, compiled, policy, horizon, budget, seed)
        if last.feasible:
            return last
        if policy.planned_completion_hard and last.status == "INFEASIBLE":
            return last
        # A congested slice is not a proof for a flexible-date scenario, and a
        # timed-out slice still has budget left. Both cases grow the horizon
        # while the bound and the clock allow it.
        if horizon >= bound_weeks or deadline - time.monotonic() <= 0.01:
            break
        horizon = min(bound_weeks, horizon + growth_step)
        growth_step *= 2

    assert last is not None
    return _finalize_flexible(last, policy, bound_weeks)


def _finalize_flexible(
    last: SolverResult, policy: ScenarioPolicy, bound_weeks: int
) -> SolverResult:
    """Relabel a flexible-date infeasibility as an unfinished search."""

    if last.status == "INFEASIBLE" and not policy.planned_completion_hard:
        # A flexible-date schedule exists by the safe bound, so an INFEASIBLE at
        # the implementation bound is not a proof. Report it as unfinished.
        return last.model_copy(
            update={
                "status": "UNKNOWN",
                "infeasibility_reasons": tuple(last.infeasibility_reasons)
                + (
                    f"adaptive horizon reached the {bound_weeks}-week implementation "
                    "bound without a complete incumbent",
                ),
            }
        )
    return last


def _attempt_budget(time_limit_seconds: float, remaining: float) -> float:
    """Per-attempt time slice: half of what is left, never the whole budget."""

    if remaining <= 0:
        return 0.01
    return max(0.01, remaining * 0.5)


def search_workers() -> int:
    """Worker count for CP-SAT. Default 1 keeps runs deterministic; set
    RAO_SEARCH_WORKERS up to 64 to use a portfolio on a larger host."""

    raw = os.environ.get("RAO_SEARCH_WORKERS", "1")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "RAO_SEARCH_WORKERS must be an integer between 1 and 64"
        ) from exc
    if not 1 <= value <= 64:
        raise ValueError("RAO_SEARCH_WORKERS must be between 1 and 64")
    return value


def _greedy_hint_rows(
    compiled: CompiledInstance,
    variables: SolverVariables,
    greedy: GreedySolution,
) -> tuple[list[AccessPlacement], list[OccupancyPlacement]]:
    """Project a greedy schedule into the published access/occupancy rows.

    The co-share labels are the ones the engine will emit after a solve, so the
    witness gate checks exactly the physical facts the greedy schedule carries.
    """

    access_rows: list[AccessPlacement] = []
    occupied: list[tuple[str, int, str, int]] = []
    sequence: dict[str, int] = defaultdict(int)
    for placement in greedy.placements:
        activity = compiled.activities[placement.activity_id]
        sequence[placement.activity_id] += 1
        access_rows.append(
            AccessPlacement(
                activity_id=placement.activity_id,
                access_seq=sequence[placement.activity_id],
                week=placement.week,
                eclo=placement.eclo,
                access_night=1,
                physical_night=placement.physical_night,
            )
        )
        for location_id in dict.fromkeys(activity.occupied_locations):
            occupied.append(
                (
                    placement.activity_id,
                    placement.week,
                    location_id,
                    placement.physical_night,
                )
            )
    occupancy_rows = _assign_co_share_groups(
        compiled, variables.activity_order, occupied
    )
    return access_rows, occupancy_rows


def _witness_checked_greedy(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    variables: SolverVariables,
    total_weeks: int,
) -> GreedySolution | None:
    """Return a greedy schedule only when the independent witness accepts it.

    This is a fail-closed gate. A greedy miss or a witness failure returns
    ``None`` so the normal CP-SAT search runs without a hint and safety
    semantics are untouched.
    """

    greedy = build_greedy_solution(compiled, policy, total_weeks)
    if greedy is None or not greedy.placements:
        return None
    access_rows, occupancy_rows = _greedy_hint_rows(compiled, variables, greedy)
    report = check_physical_witness(compiled, policy, access_rows, occupancy_rows)
    if not report.passed:
        return None
    return greedy


def _attempt(
    cp: Any,
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    total_weeks: int,
    budget: float,
    seed: int,
) -> SolverResult:
    """Build and solve one CP-SAT model at a fixed horizon."""

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

    greedy = _witness_checked_greedy(compiled, policy, variables, total_weeks)
    if greedy is not None:
        for placement in greedy.placements:
            key = (
                placement.activity_id,
                placement.week,
                placement.physical_night,
                int(placement.eclo),
            )
            variable = variables.x.get(key)
            if variable is not None:
                model.AddHint(variable, 1)

    solver = cp.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = search_workers()
    solver.parameters.max_time_in_seconds = float(budget)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status in (cp.OPTIMAL, cp.FEASIBLE):
        assignment = {
            key: 1 for key in variables.x if solver.Value(variables.x[key]) > 0.5
        }
        return _extract_result(
            compiled,
            policy,
            variables,
            assignment,
            status_name,
            overshoot=int(solver.Value(variables.overshoot)),
            solver_objective=solver.ObjectiveValue(),
        )

    if status_name == "UNKNOWN" and greedy is not None:
        # CP-SAT spent the budget before finding an incumbent. The greedy
        # schedule already passed the independent witness gate, so publish it as
        # the complete feasible schedule instead of an unfinished search. A
        # proven INFEASIBLE is never overridden this way.
        assignment = {
            (
                placement.activity_id,
                placement.week,
                placement.physical_night,
                int(placement.eclo),
            ): 1
            for placement in greedy.placements
        }
        return _extract_result(
            compiled,
            policy,
            variables,
            assignment,
            "FEASIBLE",
            overshoot=0,
            solver_objective=0.0,
        )

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


def _extract_result(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    variables: SolverVariables,
    assignment: dict[tuple[str, int, int, int], int],
    status_name: str,
    *,
    overshoot: int,
    solver_objective: float,
) -> SolverResult:
    access_rows: list[AccessPlacement] = []
    occupied: list[tuple[str, int, str, int]] = []
    access_weeks: dict[str, list[tuple[int, int, bool]]] = {}

    # Collect the solver's global physical nights per activity-week, then relabel
    # them to the published contract/type-local ``access_night`` by ranking the
    # physical nights the contract uses in that week. The ranking is a bijection
    # for one contract-week, so the fallback's physical-night assignment (which
    # merges same contract/type/week/local-night accesses) still witnesses the
    # solver's own feasible assignment.
    physical_by_activity: dict[str, list[tuple[int, int, bool]]] = {}
    used_physical: dict[tuple[str, int], set[int]] = defaultdict(set)
    for activity_id in variables.activity_order:
        accesses: list[tuple[int, int, bool]] = []
        for week in variables.activity_weeks[activity_id]:
            for night in variables.activity_nights[activity_id]:
                for eclo in variables.eclo_values:
                    key = (activity_id, week, night, eclo)
                    if key in variables.x and key in assignment:
                        accesses.append((week, night, bool(eclo)))
        accesses.sort(key=lambda item: (item[0], item[1]))
        physical_by_activity[activity_id] = accesses
        contract = compiled.activities[activity_id].contract_number
        for week, night, _ in accesses:
            used_physical[(contract, week)].add(night)

    local_rank: dict[tuple[str, int, int], int] = {}
    for (contract, week), nights in used_physical.items():
        for rank, night in enumerate(sorted(nights), start=1):
            local_rank[(contract, week, night)] = rank

    for activity_id in variables.activity_order:
        activity = compiled.activities[activity_id]
        contract = activity.contract_number
        accesses = physical_by_activity[activity_id]
        local_accesses: list[tuple[int, int, bool]] = []
        for sequence, (week, night, eclo) in enumerate(accesses, start=1):
            local_night = local_rank[(contract, week, night)]
            local_accesses.append((week, local_night, eclo))
            access_rows.append(
                AccessPlacement(
                    activity_id=activity_id,
                    access_seq=sequence,
                    week=week,
                    eclo=eclo,
                    access_night=local_night,
                    physical_night=night,
                )
            )
            for location_id in dict.fromkeys(activity.occupied_locations):
                occupied.append((activity_id, week, location_id, night))
        access_weeks[activity_id] = local_accesses

    occupancy_rows = _assign_co_share_groups(compiled, variables.activity_order, occupied)

    contract_results = _contract_results(compiled, access_weeks)
    breakdown = _objective_breakdown(
        compiled,
        policy,
        access_rows,
        occupancy_rows,
        contract_results,
        overshoot=overshoot,
        solver_objective=solver_objective,
    )
    binding_reasons, displacement_evidence = _binding_reasons(
        compiled, variables, access_weeks, occupancy_rows, policy, access_rows
    )
    # Displacement evidence rides on the persisted objective breakdown. It is a
    # dict of plain facts (weeks and constraint details) so the read model can
    # rebuild the explanation after a worker restart.
    breakdown["displacement_evidence"] = displacement_evidence
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
        binding_reasons=binding_reasons,
    )


def _assign_co_share_groups(
    compiled: CompiledInstance,
    activity_order: tuple[str, ...],
    occupied: list[tuple[str, int, str, int]],
) -> list[OccupancyPlacement]:
    """Label one ``co_share_group`` per physical possession slot.

    A possession is one physical night at a ``(location_id, week)``. Activities
    on different physical nights can never receive the same label, and every
    member of one label is on the same physical night. Labels are scoped to
    ``(location_id, week)`` and ordered by ascending physical night, then by the
    solver's variable order within a slot.
    """

    order_index = {activity_id: index for index, activity_id in enumerate(activity_order)}
    by_location_week: dict[tuple[str, int], dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for activity_id, week, location_id, night in occupied:
        by_location_week[(location_id, week)][night].append(activity_id)

    rows: list[OccupancyPlacement] = []
    for (location_id, week), nights in sorted(by_location_week.items()):
        for index, night in enumerate(sorted(nights), start=1):
            members = sorted(
                dict.fromkeys(nights[night]),
                key=lambda aid: order_index.get(aid, len(order_index)),
            )
            for activity_id in members:
                rows.append(
                    OccupancyPlacement(
                        activity_id=activity_id,
                        week=week,
                        location_id=location_id,
                        co_share_group=f"b{index}",
                    )
                )
    return rows


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
    access_rows: list[AccessPlacement],
    occupancy_rows: list[OccupancyPlacement],
    contract_results: list[ContractResult],
    *,
    overshoot: int,
    solver_objective: float,
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
        if excess > 0:
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
    earliness_days_total = sum(
        max(0, (result.planned_completion_date - result.simulated_completion_date).days)
        for result in contract_results
    )
    priority_overrun: dict[str, int] = defaultdict(int)
    for result in contract_results:
        priority_overrun[str(result.contract_priority)] += result.overrun_days
    priority_weighted = 0.0
    last_week_by_activity: dict[str, int] = defaultdict(int)
    for row in access_rows:
        last_week_by_activity[row.activity_id] = max(
            last_week_by_activity[row.activity_id], row.week
        )
    for activity_id, last_week in last_week_by_activity.items():
        activity = compiled.activities[activity_id]
        contract = compiled.instance.contracts[activity.contract_number]
        simulated = week_end(compiled.instance.horizon_start, last_week)
        overrun = max(0, (simulated - contract.planned_completion_date).days)
        priority_weighted += activity_weight(compiled, activity_id) * overrun

    excess_cost = policy.excess_access_nights_scored * 7 * excess_total
    eclo_cost = policy.eclo_scored * 5 * eclo_total
    if policy.scenario == "B":
        score = excess_cost + eclo_cost
    else:
        score = priority_weighted + excess_cost + eclo_cost

    return {
        "scenario": policy.scenario,
        "overrun_days_total": overrun_days_total,
        "earliness_days_total": earliness_days_total,
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
        "overshoot_units": int(overshoot),
        "solver_objective": solver_objective,
        "score": score,
        "capacity_hotspots": hotspots,
    }


def _displacement_analysis(
    compiled: CompiledInstance,
    variables: SolverVariables,
    access_rows: list[AccessPlacement],
    access_weeks: dict[str, list[tuple[int, int, bool]]],
) -> tuple[dict[str, set[str]], dict[str, dict[str, Any]]]:
    """Prove, per activity, which constraint displaced its first access later.

    The comparison is between the earliest week the activity's own planned start
    and predecessor allow and the week it was actually placed. Every intervening
    week is tested for a single admissible access given every other activity's
    actual placement. A week is admissible when at least one physical night can
    host the access without breaching closure separation, the contract workfront
    cap, the contract weekly cap, legal possession mix or location capacity.

    When every earlier week is blocked, the activity was genuinely displaced.
    The returned evidence names the earliest rejected week and the constraints
    that blocked it, so the reason codes cite a real gap rather than a limit the
    chosen placement merely happened to touch. When any earlier week admits the
    access, no displacement is claimed.
    """

    physical_by_activity_week: dict[tuple[str, int], set[int]] = defaultdict(set)
    contract_week_nights: dict[tuple[str, int], set[int]] = defaultdict(set)
    contract_night_activities: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    location_night_members: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    location_week_nights: dict[tuple[str, int], set[int]] = defaultdict(set)
    weeks_by_activity: dict[str, list[int]] = defaultdict(list)

    for row in access_rows:
        activity = compiled.activities.get(row.activity_id)
        if activity is None or row.physical_night is None:
            continue
        contract = activity.contract_number
        physical_by_activity_week[(row.activity_id, row.week)].add(row.physical_night)
        contract_week_nights[(contract, row.week)].add(row.physical_night)
        contract_night_activities[(contract, row.week, row.physical_night)].add(
            row.activity_id
        )
        for location_id in dict.fromkeys(activity.occupied_locations):
            location_night_members[
                (location_id, row.week, row.physical_night)
            ].add(row.activity_id)
            location_week_nights[(location_id, row.week)].add(row.physical_night)

    for activity_id, accesses in access_weeks.items():
        weeks_by_activity[activity_id] = sorted({week for week, _, _ in accesses})

    conflict_partners: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (left_id, right_id), conflict in sorted(
        compiled.physical_possession.closure_conflicts.items()
    ):
        if truly_co_sharable(compiled, left_id, right_id):
            continue
        code = reasons.CLOSURE_RULE_CODES.get(conflict.rule)
        if code is None:
            continue
        conflict_partners[left_id].append((right_id, code))
        conflict_partners[right_id].append((left_id, code))

    def _blockers(activity_id: str, week: int) -> dict[str, dict[str, Any]]:
        """First blocking detail per constraint for one candidate access.

        Returns an empty mapping when some physical night admits the access.
        """

        activity = compiled.activities[activity_id]
        contract = activity.contract_number
        capacity_by_location = compiled.location_capacities
        blocked: dict[str, dict[str, Any]] = {}
        for night in variables.physical_nights:
            night_blocked: dict[str, dict[str, Any]] = {}
            for partner_id, code in conflict_partners.get(activity_id, ()):
                if night in physical_by_activity_week.get((partner_id, week), set()):
                    night_blocked.setdefault(
                        code,
                        {
                            "week": week,
                            "night": night,
                            "counterpart_activity_id": partner_id,
                        },
                    )
            if night_blocked:
                for code, detail in night_blocked.items():
                    blocked.setdefault(code, detail)
                continue
            if (
                len(contract_night_activities.get((contract, week, night), set()))
                >= compiled.contract_workfronts[contract]
            ):
                night_blocked[reasons.WORKFRONT] = {
                    "week": week,
                    "night": night,
                    "used": len(
                        contract_night_activities.get((contract, week, night), set())
                    ),
                    "limit": compiled.contract_workfronts[contract],
                }
            used_nights = contract_week_nights.get((contract, week), set())
            if (
                night not in used_nights
                and len(used_nights) >= compiled.contract_weekly_caps[contract]
            ):
                night_blocked[reasons.WEEKLY_CAP] = {
                    "week": week,
                    "used": len(used_nights),
                    "limit": compiled.contract_weekly_caps[contract],
                }
            for location_id in dict.fromkeys(activity.occupied_locations):
                members = location_night_members.get((location_id, week, night))
                if members:
                    types = [compiled.activities[member].access_type for member in members]
                    types.append(activity.access_type)
                    if not legal_access_mix(types):
                        night_blocked[reasons.POSSESSION_MIX] = {
                            "week": week,
                            "night": night,
                            "location_id": location_id,
                            "occupied_by": sorted(members),
                        }
                elif (
                    len(location_week_nights.get((location_id, week), set()))
                    >= capacity_by_location.get(location_id, 0)
                ):
                    night_blocked[reasons.CAPACITY] = {
                        "week": week,
                        "night": night,
                        "location_id": location_id,
                        "used": len(location_week_nights.get((location_id, week), set())),
                        "capacity": capacity_by_location.get(location_id, 0),
                    }
            if not night_blocked:
                return {}
            for code, detail in night_blocked.items():
                blocked.setdefault(code, detail)
        return blocked

    codes_per_activity: dict[str, set[str]] = defaultdict(set)
    evidence: dict[str, dict[str, Any]] = {}
    for activity_id in sorted(weeks_by_activity):
        weeks = weeks_by_activity[activity_id]
        if not weeks:
            continue
        activity = compiled.activities[activity_id]
        actual_first_week = weeks[0]
        planned_earliest_week = max(1, activity.planned_start_week)
        predecessor_id = activity.predecessor_activity_id
        if predecessor_id is not None:
            predecessor_weeks = weeks_by_activity.get(predecessor_id, [])
            if predecessor_weeks:
                planned_earliest_week = max(
                    planned_earliest_week, predecessor_weeks[-1] + 1
                )

        rejected: dict[int, dict[str, dict[str, Any]]] = {}
        earliest_possible_week = actual_first_week
        for week in range(planned_earliest_week, actual_first_week):
            blockers = _blockers(activity_id, week)
            if not blockers:
                earliest_possible_week = week
                break
            rejected[week] = blockers

        displaced = earliest_possible_week == actual_first_week and bool(rejected)
        binding_week = min(rejected) if displaced else None
        binding_details = rejected.get(binding_week, {}) if binding_week else {}
        # POSSESSION_MIX keeps its documented meaning: it is only earned by
        # work that actually shares a co_share_group. A mix failure only shows up
        # in the rejected-week details, never as a displacement reason code.
        binding_constraints = (
            sorted(
                code
                for code in binding_details
                if code in _DISPLACEMENT_REASON_CODES
            )
            if displaced
            else []
        )
        if displaced:
            codes_per_activity[activity_id].update(binding_constraints)

        entry: dict[str, Any] = {
            "planned_earliest_week": planned_earliest_week,
            "actual_first_week": actual_first_week,
            "earliest_possible_week": earliest_possible_week,
            "displaced": displaced,
            "rejected_weeks": sorted(rejected) if displaced else [],
            "binding_week": binding_week,
            "binding_constraints": binding_constraints,
            "binding_details": binding_details,
        }
        evidence[activity_id] = entry

    return codes_per_activity, evidence


def _binding_reasons(
    compiled: CompiledInstance,
    variables: SolverVariables,
    access_weeks: dict[str, list[tuple[int, int, bool]]],
    occupancy_rows: list[OccupancyPlacement],
    policy: ScenarioPolicy,
    access_rows: list[AccessPlacement],
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    codes_per_activity: dict[str, set[str]] = defaultdict(set)
    horizon = compiled.instance.horizon_weeks
    group_members: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    occupancy_by_activity: dict[str, list[OccupancyPlacement]] = defaultdict(list)
    for row in occupancy_rows:
        group_members[(row.location_id, row.week, row.co_share_group)].add(
            row.activity_id
        )
        occupancy_by_activity[row.activity_id].append(row)

    weeks_by_activity: dict[str, set[int]] = {}
    for activity_id, accesses in access_weeks.items():
        weeks_by_activity[activity_id] = {week for week, _, _ in accesses}

    # Physical possession evidence: closure, mirroring and interchange come
    # straight from the compiled closure graph, keyed by the shared close
    # location rather than an equal local night number.
    possession = compiled.physical_possession
    for (left_id, right_id), conflict in sorted(possession.closure_conflicts.items()):
        if truly_co_sharable(compiled, left_id, right_id):
            continue
        if not weeks_by_activity.get(left_id, set()) & weeks_by_activity.get(right_id, set()):
            continue
        code = reasons.CLOSURE_RULE_CODES.get(conflict.rule)
        if code is None:
            continue
        codes_per_activity[left_id].add(code)
        codes_per_activity[right_id].add(code)

    # Capacity, weekly-cap and workfront codes are only earned by displaced work:
    # they name the constraint that rejected an earlier week, never a limit the
    # chosen placement merely touched.
    displacement_codes, displacement_evidence = _displacement_analysis(
        compiled, variables, access_rows, access_weeks
    )
    for activity_id, extra_codes in displacement_codes.items():
        codes_per_activity[activity_id].update(extra_codes)

    for activity_id in variables.activity_order:
        accesses = access_weeks.get(activity_id, [])
        if not accesses:
            continue
        activity = compiled.activities[activity_id]
        first_week = accesses[0][0]
        codes = codes_per_activity[activity_id]
        if first_week == max(1, activity.planned_start_week):
            codes.add(reasons.PLANNED_START)
        if first_week > horizon:
            codes.add(reasons.HORIZON_EXTENDED)
        if activity.predecessor_activity_id is not None:
            predecessor_accesses = access_weeks.get(activity.predecessor_activity_id, [])
            if predecessor_accesses and first_week == predecessor_accesses[-1][0] + 1:
                codes.add(reasons.PREDECESSOR)
        if policy.eclo_window == "two_week_per_line" and any(
            eclo for _, _, eclo in accesses
        ):
            codes.add(reasons.ECLO_WINDOW)
        activity_occupancy = occupancy_by_activity.get(activity_id, [])
        # Possession-mix and co-share packing only describe work that actually
        # shares a co_share_group. An activity alone in its own group never
        # claims either, even when other groups sit at the same location-week.
        if any(
            len(group_members[(row.location_id, row.week, row.co_share_group)]) > 1
            for row in activity_occupancy
        ):
            codes.add(reasons.CO_SHARE_PACKED)
            codes.add(reasons.POSSESSION_MIX)
        contract = activity.contract_number
        last_week = accesses[-1][0]
        simulated_completion = week_end(compiled.instance.horizon_start, last_week)
        planned_completion = compiled.instance.contracts[
            contract
        ].planned_completion_date
        if simulated_completion > planned_completion:
            codes.add(reasons.PRIORITY_OVERRUN)

    return (
        {
            activity_id: sorted(codes)
            for activity_id, codes in sorted(codes_per_activity.items())
        },
        displacement_evidence,
    )


def _infeasibility_reasons(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    total_weeks: int,
    status_name: str,
) -> list[str]:
    messages: list[str] = []
    horizon_start = compiled.instance.horizon_start
    for activity_id in sorted(compiled.activities):
        activity = compiled.activities[activity_id]
        if activity.planned_start_week > total_weeks:
            messages.append(
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
                    messages.append(
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
                    messages.append(
                        f"activity {activity.activity_id} needs {required_weeks} weeks "
                        f"of access but only {weeks_available} are available before "
                        f"contract {contract_number}'s planned completion"
                    )
    if not messages:
        messages.append(
            f"CP-SAT returned {status_name}: the hard {policy.scenario}-scenario "
            f"constraints cannot be satisfied within the {total_weeks}-week horizon "
            "after adaptive growth"
        )
    return messages


__all__ = [
    "RailPlanRequest",
    "Scenario",
    "completion_bound",
    "resolve_total_weeks",
    "solve",
    "solve_request",
]
