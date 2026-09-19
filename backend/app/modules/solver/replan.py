"""Dynamic disruption impact assessment and minimal-churn replanning.

This module serves ``F-BONUS-001``. It has three jobs:

1. turn a typed disruption into a *disrupted* compiled instance plus the extra
   hard facts the model needs (banned nights, banned location-weeks);
2. assess the impact of the disruption against the persisted schedule of a
   completed job, without re-solving;
3. re-solve with the existing CP-SAT machinery, adding a churn penalty that
   rewards keeping the original physical placements, then report the before and
   after diff.

Safety semantics are inherited unchanged. Constraint construction reuses
:mod:`app.modules.solver.constraints`, extraction reuses the engine's own
extraction, the greedy incumbent stays witness-gated, and every feasible replan
is re-checked by the independent physical witness. A witness failure is reported
as ``UNSAFE`` and the schedule is withheld, never published.

.. warning::

   ``engine.py`` is intentionally not modified. A few private engine helpers
   (objective-free extraction, infeasibility prose, gated greedy, horizon
   finalisation) are imported so the replan sees exactly the same safety
   semantics. If those helpers change, this module must be re-checked.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.domain.rail.compiled import CompiledInstance
from app.domain.rail.instance_model import (
    Activity,
    PlanningInstance,
    build_successor_index,
)
from app.domain.schemas import (
    LocationUnavailable,
    NightUnavailable,
    SupplyDrop,
    UrgentActivityInjection,
)
from app.modules.compiler.policy import (
    ECLO_NIGHT_COST,
    EXCESS_ACCESS_NIGHT_COST,
    ScenarioPolicy,
    get_policy,
)
from app.modules.compiler.rule_compiler import compile_instance
from app.modules.solver import engine as _engine
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
from app.modules.solver.objectives import (
    OBJECTIVE_SCALE,
    OVERSHOOT_WEIGHT,
    activity_weight,
)
from app.modules.solver.results import SolverResult
from app.modules.solver.variables import SolverVariables, build_variables
from app.modules.validator.witness import PhysicalWitnessReport, check_physical_witness

# Churn is a soft cost. The weight sits far above the scaled scenario objective
# so keeping an original physical placement dominates any scenario tie-break,
# while hard constraints still decide feasibility. It is deliberately a
# multiple of the objective scale and an integer, which CP-SAT prefers.
CHURN_ACCESS_WEIGHT = 100_000

_NIGHT_KEY = tuple[int, int]
_LOCATION_WEEK_KEY = tuple[str, int]


@dataclass(frozen=True)
class ChurnReference:
    """The original physical placements a replan is asked to preserve.

    ``placements`` maps an activity id to the ordered set of ``(week, physical
    night)`` slots it occupied in the source schedule. Rows without a witness
    physical night cannot be matched and are ignored.
    """

    placements: dict[str, tuple[tuple[int, int], ...]]

    @property
    def access_count(self) -> int:
        return sum(len(slots) for slots in self.placements.values())


@dataclass(frozen=True)
class DisruptionEffects:
    """The hard facts a disruption adds on top of the disrupted instance."""

    unavailable_locations: frozenset[str] = frozenset()
    forbidden_location_weeks: frozenset[_LOCATION_WEEK_KEY] = frozenset()
    unavailable_nights: frozenset[int] = frozenset()
    forbidden_night_weeks: frozenset[_NIGHT_KEY] = frozenset()


@dataclass(frozen=True)
class ReplanSolution:
    """One minimal-churn replan outcome, safe or honestly infeasible."""

    result: SolverResult
    witness: PhysicalWitnessReport | None
    safe: bool
    churn_moved: int
    churn_weight: int
    objective_breakdown: dict[str, Any]


def build_reference(access_rows: Iterable[Any]) -> ChurnReference:
    """Build a churn reference from persisted access rows."""

    grouped: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row in access_rows:
        activity_id = getattr(row, "activity_id", None)
        week = getattr(row, "week", None)
        night = getattr(row, "physical_night", None)
        if activity_id is None or week is None or night is None:
            continue
        grouped[str(activity_id)].add((int(week), int(night)))
    return ChurnReference(
        {
            activity_id: tuple(sorted(slots))
            for activity_id, slots in sorted(grouped.items())
        }
    )


def _inject_urgent(
    instance: PlanningInstance, spec: UrgentActivityInjection
) -> PlanningInstance:
    """Return a new instance with one urgent activity added."""

    contract = instance.contracts.get(spec.contract_number)
    if contract is None:
        raise KeyError(
            f"urgent activity {spec.activity_id!r} references unknown contract "
            f"{spec.contract_number!r}"
        )
    activities = dict(instance.activities)
    if spec.activity_id in activities:
        raise KeyError(f"urgent activity {spec.activity_id!r} already exists")
    activities[spec.activity_id] = Activity(
        activity_id=spec.activity_id,
        contract_number=spec.contract_number,
        activity_type=spec.activity_type or contract.activity_type,
        start_location_id=spec.start_location_id,
        end_location_id=spec.end_location_id,
        total_accesses=spec.total_accesses,
        planned_start_date=spec.planned_start_date,
        predecessor_activity_id=spec.predecessor_activity_id,
        activity_priority=spec.activity_priority,
    )
    predecessors = dict(instance.predecessors)
    if spec.predecessor_activity_id is not None:
        predecessors[spec.activity_id] = spec.predecessor_activity_id
    return instance.model_copy(
        update={
            "activities": activities,
            "predecessors": predecessors,
            "successors": build_successor_index(predecessors),
        }
    )


def resolve_disruptions(
    compiled: CompiledInstance, disruptions: Iterable[Any]
) -> tuple[CompiledInstance, DisruptionEffects]:
    """Apply disruptions and return the disrupted instance and hard facts.

    Supply drops change the compiled location capacity. Location and night bans
    are kept as explicit hard facts so they bind under every scenario policy,
    including Scenario B's soft capacity.
    """

    disruptions = tuple(disruptions)
    base = compiled
    if any(isinstance(item, UrgentActivityInjection) for item in disruptions):
        instance = compiled.instance
        for item in disruptions:
            if isinstance(item, UrgentActivityInjection):
                instance = _inject_urgent(instance, item)
        base = compile_instance(instance)

    capacities = dict(base.location_capacities)
    unavailable_locations: set[str] = set()
    forbidden_location_weeks: set[_LOCATION_WEEK_KEY] = set()
    unavailable_nights: set[int] = set()
    forbidden_night_weeks: set[_NIGHT_KEY] = set()

    for item in disruptions:
        if isinstance(item, SupplyDrop):
            capacities[item.location_id] = item.new_supply
        elif isinstance(item, LocationUnavailable):
            if item.weeks is None:
                unavailable_locations.add(item.location_id)
                capacities[item.location_id] = 0
            else:
                for week in item.weeks:
                    forbidden_location_weeks.add((item.location_id, int(week)))
        elif isinstance(item, NightUnavailable):
            if item.weeks is None:
                unavailable_nights.add(int(item.physical_night))
            else:
                for week in item.weeks:
                    forbidden_night_weeks.add((int(week), int(item.physical_night)))

    disrupted = base.model_copy(update={"location_capacities": capacities})
    return disrupted, DisruptionEffects(
        unavailable_locations=frozenset(unavailable_locations),
        forbidden_location_weeks=frozenset(forbidden_location_weeks),
        unavailable_nights=frozenset(unavailable_nights),
        forbidden_night_weeks=frozenset(forbidden_night_weeks),
    )


# ---------------------------------------------------------------------------
# Impact assessment (persisted evidence only, no re-solve)
# ---------------------------------------------------------------------------


def _slot_sort_key(slot: tuple[int, int | None]) -> tuple[int, int]:
    week, night = slot
    return (week, -1 if night is None else night)


def _slot_map(rows: Iterable[Any]) -> dict[str, list[tuple[int, int | None]]]:
    grouped: dict[str, set[tuple[int, int | None]]] = defaultdict(set)
    for row in rows:
        activity_id = getattr(row, "activity_id", None)
        week = getattr(row, "week", None)
        if activity_id is None or week is None:
            continue
        grouped[str(activity_id)].add((int(week), getattr(row, "physical_night", None)))
    return {
        activity_id: sorted(slots, key=_slot_sort_key)
        for activity_id, slots in sorted(grouped.items())
    }


def assess_impact(
    compiled: CompiledInstance,
    disruptions: Iterable[Any],
    access_rows: Iterable[Any],
    occupancy_rows: Iterable[Any],
    contract_results: Iterable[Any],
) -> dict[str, Any]:
    """Report what a disruption invalidates, from persisted evidence only."""

    disruptions = tuple(disruptions)
    access_list = list(access_rows)
    occupancy_list = list(occupancy_rows)
    contract_list = list(contract_results)

    access_by_activity_week: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for row in access_list:
        access_by_activity_week[(str(row.activity_id), int(row.week))].append(row)

    groups_by_location_week: dict[tuple[str, int], set[str]] = defaultdict(set)
    members_by_group: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    for row in occupancy_list:
        location_id = str(row.location_id)
        week = int(row.week)
        group = str(row.co_share_group)
        groups_by_location_week[(location_id, week)].add(group)
        members_by_group[(location_id, week, group)].add(str(row.activity_id))

    invalid: list[dict[str, Any]] = []
    invalid_markers: set[tuple[str, int, int | None]] = set()
    affected_activities: set[str] = set()
    affected_contracts: set[str] = set()
    affected_location_weeks: list[dict[str, Any]] = []
    injected_accesses = 0
    notes: list[str] = []

    def mark_invalid(
        activity_id: str, week: int, night: int | None, location_id: str | None, reason: str
    ) -> None:
        marker = (activity_id, week, night)
        affected_activities.add(activity_id)
        if marker in invalid_markers:
            return
        invalid_markers.add(marker)
        invalid.append(
            {
                "activity_id": activity_id,
                "week": week,
                "physical_night": night,
                "location_id": location_id,
                "reason": reason,
            }
        )

    def _mark_activity_week(
        activity_id: str, week: int, location_id: str | None, reason: str
    ) -> None:
        for row in access_by_activity_week.get((activity_id, week), []):
            mark_invalid(
                activity_id,
                week,
                getattr(row, "physical_night", None),
                location_id,
                reason,
            )

    for item in disruptions:
        if isinstance(item, SupplyDrop):
            location_id = item.location_id
            for (loc, week), groups in sorted(groups_by_location_week.items()):
                if loc != location_id:
                    continue
                used = len(groups)
                if used <= item.new_supply:
                    continue
                excess = used - item.new_supply
                affected_location_weeks.append(
                    {
                        "location_id": loc,
                        "week": week,
                        "used": used,
                        "capacity": item.new_supply,
                        "excess": excess,
                        "reason": "supply_drop",
                    }
                )
                overflow = sorted(groups)[item.new_supply :]
                for group in overflow:
                    for activity_id in sorted(members_by_group[(loc, week, group)]):
                        _mark_activity_week(activity_id, week, loc, "supply_drop")
            if location_id not in compiled.location_capacities:
                notes.append(f"supplied location {location_id!r} is not in the instance")
        elif isinstance(item, LocationUnavailable):
            for (loc, week), groups in sorted(groups_by_location_week.items()):
                if loc != item.location_id:
                    continue
                if item.weeks is not None and week not in item.weeks:
                    continue
                affected_location_weeks.append(
                    {
                        "location_id": loc,
                        "week": week,
                        "used": len(groups),
                        "capacity": 0,
                        "excess": len(groups),
                        "reason": "location_unavailable",
                    }
                )
                for group in sorted(groups):
                    for activity_id in sorted(members_by_group[(loc, week, group)]):
                        _mark_activity_week(
                            activity_id, week, loc, "location_unavailable"
                        )
        elif isinstance(item, NightUnavailable):
            for row in access_list:
                if getattr(row, "physical_night", None) != item.physical_night:
                    continue
                if item.weeks is not None and int(row.week) not in item.weeks:
                    continue
                mark_invalid(
                    str(row.activity_id),
                    int(row.week),
                    int(row.physical_night),
                    None,
                    "night_unavailable",
                )
        elif isinstance(item, UrgentActivityInjection):
            injected_accesses += item.total_accesses
            affected_activities.add(item.activity_id)
            affected_contracts.add(item.contract_number)

    for activity_id in sorted(affected_activities):
        compiled_activity = compiled.activities.get(activity_id)
        if compiled_activity is not None:
            affected_contracts.add(compiled_activity.contract_number)

    overrun_before = sum(max(0, int(row.overrun_days)) for row in contract_list)
    contracts_overrunning = sum(
        1 for row in contract_list if int(row.overrun_days) > 0
    )
    displaced = len(invalid) + injected_accesses
    access_before = len(access_list)

    return {
        "invalid_placements": invalid,
        "affected_activities": sorted(affected_activities),
        "affected_contracts": sorted(affected_contracts),
        "affected_location_weeks": sorted(
            affected_location_weeks,
            key=lambda entry: (entry["location_id"], entry["week"], entry["reason"]),
        ),
        "workload": {
            "access_nights_before": access_before,
            "invalid_access_nights": len(invalid),
            "injected_access_nights": injected_accesses,
            "access_nights_after_lower_bound": access_before - len(invalid) + injected_accesses,
        },
        "overrun": {
            "overrun_days_before": overrun_before,
            "contracts_overrunning_before": contracts_overrunning,
            "displaced_access_nights": displaced,
            "worst_case_additional_overrun_days": 7 * displaced,
            "worst_case_overrun_days": overrun_before + 7 * displaced,
        },
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Minimal-churn replan solve
# ---------------------------------------------------------------------------


def _churn_terms(
    variables: SolverVariables, reference: ChurnReference
) -> list[Any]:
    """A soft reward for keeping each original physical placement."""

    terms: list[Any] = []
    for activity_id in sorted(reference.placements):
        for week, night in reference.placements[activity_id]:
            present = variables.present.get((activity_id, week, night))
            if present is None:
                continue
            terms.append(CHURN_ACCESS_WEIGHT * (1 - present))
    return terms


def _build_objective_with_churn(
    model: Any,
    compiled: CompiledInstance,
    variables: SolverVariables,
    policy: ScenarioPolicy,
    reference: ChurnReference,
) -> None:
    """Mirror the scenario objective and add the churn penalty.

    ``objectives.build_objective`` calls ``model.Minimize`` itself, so the churn
    term cannot be attached afterwards. The scenario terms are rebuilt here with
    the exact same coefficients and scaled the same way.
    """

    terms: list[Any] = []
    for activity_id in variables.activity_order:
        scaled = round(activity_weight(compiled, activity_id) * OBJECTIVE_SCALE)
        if policy.overrun_scored and scaled:
            terms.append(scaled * variables.activity_overrun[activity_id])
    for variable in variables.excess.values():
        terms.append(EXCESS_ACCESS_NIGHT_COST * OBJECTIVE_SCALE * variable)
    for key, variable in variables.x.items():
        if key[3] == 1:
            terms.append(ECLO_NIGHT_COST * OBJECTIVE_SCALE * variable)
    terms.append(OVERSHOOT_WEIGHT * variables.overshoot)
    terms.extend(_churn_terms(variables, reference))
    model.Minimize(sum(terms))


def _add_disruption_constraints(
    model: Any, variables: SolverVariables, effects: DisruptionEffects
) -> None:
    """Forbid nights and location-weeks the disruption closed."""

    if effects.unavailable_nights or effects.forbidden_night_weeks:
        for key, variable in variables.x.items():
            _activity_id, week, night, _eclo = key
            if (
                night in effects.unavailable_nights
                or (week, night) in effects.forbidden_night_weeks
            ):
                model.Add(variable == 0)

    forbidden_location_weeks = set(effects.forbidden_location_weeks)
    for location_id in effects.unavailable_locations:
        for week in variables.weeks:
            forbidden_location_weeks.add((location_id, week))
    for location_id, week in sorted(forbidden_location_weeks):
        for night in variables.physical_nights:
            slot = variables.location_slot_used.get((location_id, week, night))
            if slot is not None:
                model.Add(slot == 0)


def _attempt(
    cp: Any,
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    total_weeks: int,
    budget: float,
    seed: int,
    reference: ChurnReference,
    effects: DisruptionEffects,
) -> SolverResult:
    """Build and solve one churn-weighted CP-SAT model at a fixed horizon."""

    model = cp.CpModel()
    variables = build_variables(model, compiled, policy, total_weeks)

    add_linking_constraints(model, compiled, variables)
    add_time_constraints(model, compiled, variables)
    add_caps_constraints(model, compiled, variables)
    add_possession_constraints(model, compiled, variables)
    add_capacity_constraints(model, compiled, variables, policy)
    add_completion_constraints(model, compiled, variables, policy)
    add_eclo_constraints(model, compiled, variables, policy)
    _build_objective_with_churn(model, compiled, variables, policy, reference)
    _add_disruption_constraints(model, variables, effects)

    greedy = _engine._witness_checked_greedy(compiled, policy, variables, total_weeks)
    if greedy is not None:
        for placement in greedy.placements:
            variable = variables.x.get(
                (
                    placement.activity_id,
                    placement.week,
                    placement.physical_night,
                    int(placement.eclo),
                )
            )
            if variable is not None:
                model.AddHint(variable, 1)

    solver = cp.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = float(budget)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status in (cp.OPTIMAL, cp.FEASIBLE):
        assignment = {
            key: 1 for key in variables.x if solver.Value(variables.x[key]) > 0.5
        }
        return _engine._extract_result(
            compiled,
            policy,
            variables,
            assignment,
            status_name,
            overshoot=int(solver.Value(variables.overshoot)),
            solver_objective=solver.ObjectiveValue(),
        )

    if status_name == "UNKNOWN" and greedy is not None:
        assignment = {
            (
                placement.activity_id,
                placement.week,
                placement.physical_night,
                int(placement.eclo),
            ): 1
            for placement in greedy.placements
        }
        return _engine._extract_result(
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
        infeasibility_reasons=_engine._infeasibility_reasons(
            compiled, policy, total_weeks, status_name
        ),
    )


def _solve_churn(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    reference: ChurnReference,
    effects: DisruptionEffects,
    time_limit_seconds: float,
    seed: int,
    horizon_extension_weeks: int,
) -> SolverResult:
    """Solve one disrupted scenario, growing the horizon as the engine does."""

    cp = load_cp_model()
    initial_weeks = _engine.resolve_total_weeks(compiled, horizon_extension_weeks)
    if horizon_extension_weeks <= 0:
        last = _attempt(
            cp,
            compiled,
            policy,
            initial_weeks,
            time_limit_seconds,
            seed,
            reference,
            effects,
        )
        return _engine._finalize_flexible(last, policy, initial_weeks)

    growth_step = max(1, horizon_extension_weeks)
    if policy.planned_completion_hard:
        bound_weeks = initial_weeks
    else:
        bound_weeks = max(initial_weeks, _engine.completion_bound(compiled))
    deadline = time.monotonic() + float(time_limit_seconds)

    horizon = initial_weeks
    last: SolverResult | None = None
    while True:
        remaining = deadline - time.monotonic()
        if last is not None and remaining <= 0.01:
            break
        budget = _engine._attempt_budget(time_limit_seconds, remaining)
        last = _attempt(
            cp, compiled, policy, horizon, budget, seed, reference, effects
        )
        if last.feasible:
            return last
        if policy.planned_completion_hard and last.status == "INFEASIBLE":
            return last
        if horizon >= bound_weeks or deadline - time.monotonic() <= 0.01:
            break
        horizon = min(bound_weeks, horizon + growth_step)
        growth_step *= 2

    assert last is not None
    return _engine._finalize_flexible(last, policy, bound_weeks)


def _reuse_count(reference: ChurnReference, result: SolverResult) -> int:
    new_slots: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row in result.access:
        if row.physical_night is None:
            continue
        new_slots[row.activity_id].add((row.week, row.physical_night))
    reused = 0
    for activity_id, slots in reference.placements.items():
        new = new_slots.get(activity_id, set())
        reused += sum(1 for slot in slots if slot in new)
    return reused


def count_moved(reference: ChurnReference, result: SolverResult) -> int:
    """How many original access placements the replan did not keep exactly."""

    return max(0, reference.access_count - _reuse_count(reference, result))


def solve_replan(
    compiled: CompiledInstance,
    scenario: str,
    disruptions: Iterable[Any],
    reference: ChurnReference,
    *,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    seed: int = DEFAULT_SEED,
    horizon_extension_weeks: int = DEFAULT_HORIZON_EXTENSION_WEEKS,
) -> ReplanSolution:
    """Re-optimize under the disruption with minimal churn to the original."""

    policy = get_policy(scenario)
    disrupted, effects = resolve_disruptions(compiled, disruptions)
    result = _solve_churn(
        disrupted,
        policy,
        reference,
        effects,
        time_limit_seconds,
        seed,
        horizon_extension_weeks,
    )

    if not result.feasible:
        return ReplanSolution(
            result=result,
            witness=None,
            safe=False,
            churn_moved=0,
            churn_weight=CHURN_ACCESS_WEIGHT,
            objective_breakdown=dict(result.objective_breakdown),
        )

    witness = check_physical_witness(
        disrupted, policy, result.access, result.occupancy
    )
    moved = count_moved(reference, result)
    breakdown = dict(result.objective_breakdown)
    breakdown["churn"] = {
        "moved_accesses": moved,
        "reference_accesses": reference.access_count,
        "access_weight": CHURN_ACCESS_WEIGHT,
    }
    result = result.model_copy(update={"objective_breakdown": breakdown})

    safe = bool(witness.passed)
    if not safe:
        # Fail closed: never publish a replan the independent witness rejects.
        result = result.model_copy(
            update={
                "feasible": False,
                "status": "UNSAFE",
                "access": (),
                "occupancy": (),
                "contract_results": (),
                "contract_completion": {},
            }
        )
    return ReplanSolution(
        result=result,
        witness=witness,
        safe=safe,
        churn_moved=moved,
        churn_weight=CHURN_ACCESS_WEIGHT,
        objective_breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# Before/after diff
# ---------------------------------------------------------------------------


def diff_against(
    access_rows: Iterable[Any],
    result: SolverResult,
    *,
    required_activities: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Compare a source schedule with a replan, by physical placement."""

    original = _slot_map(access_rows)
    replan = _slot_map(result.access)

    replaced: dict[str, set[tuple[int, int | None]]] = {}
    for activity_id, slots in replan.items():
        replaced[activity_id] = set(slots)

    moved: list[dict[str, Any]] = []
    unchanged: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    reused = 0

    for activity_id in sorted(set(original) | set(replan)):
        before = original.get(activity_id)
        after = replan.get(activity_id)
        if before is not None and after is None:
            removed.append(activity_id)
            continue
        if before is None and after is not None:
            added.append(activity_id)
            continue
        assert before is not None and after is not None
        before_set = set(before)
        after_set = replaced[activity_id]
        reused += len(before_set & after_set)
        if before == after:
            unchanged.append(activity_id)
            continue
        moved.append(
            {
                "activity_id": activity_id,
                "from": [list(slot) for slot in before if slot not in after_set],
                "to": [list(slot) for slot in after if slot not in before_set],
            }
        )

    required = set(required_activities or ())
    if not result.feasible:
        candidates = required | set(original)
    else:
        placed = set(replan)
        candidates = {activity_id for activity_id in required if activity_id not in placed}
    newly_unsatisfiable = sorted(candidates)

    original_accesses = sum(len(slots) for slots in original.values())
    return {
        "moved": moved,
        "unchanged": unchanged,
        "added": added,
        "removed": removed,
        "newly_unsatisfiable": newly_unsatisfiable,
        "totals": {
            "original_accesses": original_accesses,
            "replan_accesses": sum(len(slots) for slots in replan.values()),
            "reused_accesses": reused,
            "moved_accesses": original_accesses - reused,
            "moved_activities": len(moved),
            "unchanged_activities": len(unchanged),
        },
    }


__all__ = [
    "CHURN_ACCESS_WEIGHT",
    "ChurnReference",
    "DisruptionEffects",
    "ReplanSolution",
    "assess_impact",
    "build_reference",
    "count_moved",
    "diff_against",
    "resolve_disruptions",
    "solve_replan",
]
