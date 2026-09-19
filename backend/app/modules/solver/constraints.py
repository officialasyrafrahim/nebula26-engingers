"""Hard constraints for the rail CP-SAT model.

Every constraint is derived from the compiled instance and the scenario policy;
nothing is hard-coded per activity. Constraint groups are tagged in comments
with the validator rule names so explanations can point back at them.
"""

from __future__ import annotations

from typing import Any

from app.domain.rail.compiled import CompiledInstance
from app.domain.rail.keys import parse_location_id
from app.modules.compiler.mixes import C_ONLY_LIMIT, PC_COWORKER_LIMIT
from app.modules.compiler.policy import ScenarioPolicy
from app.modules.solver.possession import truly_co_sharable
from app.modules.solver.variables import SolverVariables


def _affected_lines(compiled: CompiledInstance, activity_id: str) -> frozenset[str]:
    """Lines whose infrastructure an activity's closures touch."""

    lines: set[str] = set()
    for location_id in compiled.activities[activity_id].closed_locations:
        try:
            lines.add(parse_location_id(location_id).line_code)
        except ValueError:  # pragma: no cover - locations are pre-validated
            continue
    return frozenset(lines)


def add_linking_constraints(
    model: Any, compiled: CompiledInstance, variables: SolverVariables
) -> None:
    """Link ``present`` and ``week_present`` to the underlying access flags."""

    for (activity_id, week, night), present in variables.present.items():
        terms = [
            variables.x[(activity_id, week, night, eclo)]
            for eclo in variables.eclo_values
        ]
        model.Add(present == sum(terms))

    for (activity_id, week), week_present in variables.week_present.items():
        nights = variables.activity_nights[activity_id]
        terms = [
            variables.present[(activity_id, week, night)]
            for night in nights
            if (activity_id, week, night) in variables.present
        ]
        model.Add(week_present == sum(terms))

    # ``present_at_or_after[a, w]`` is true when ``a`` has an access in week
    # ``w`` or any later week. It lets the predecessor clause be reified so the
    # successor's absence does not constrain the predecessor.
    for activity_id in variables.activity_order:
        for week in range(variables.total_weeks, 0, -1):
            at_or_after = variables.present_at_or_after[(activity_id, week)]
            following = variables.present_at_or_after.get((activity_id, week + 1), 0)
            current = variables.week_present.get((activity_id, week))
            if current is None:
                model.Add(at_or_after == following)
                continue
            model.Add(at_or_after >= current)
            model.Add(at_or_after >= following)
            model.Add(at_or_after <= current + following)


def add_time_constraints(
    model: Any, compiled: CompiledInstance, variables: SolverVariables
) -> None:
    """Rule ``workload``, ``allocation`` (one access/week), ``predecessor``."""

    total_units: list[Any] = []
    target_units = 0
    for activity_id in variables.activity_order:
        activity = compiled.activities[activity_id]
        weeks = variables.activity_weeks[activity_id]
        nights = variables.activity_nights[activity_id]
        activity_units: list[Any] = []
        for week in weeks:
            # Rule ``allocation``: at most one access per activity-week.
            accesses = [
                variables.x[(activity_id, week, night, eclo)]
                for night in nights
                for eclo in variables.eclo_values
            ]
            if accesses:
                model.Add(sum(accesses) <= 1)
            for night in nights:
                for eclo in variables.eclo_values:
                    weight = 2 if eclo == 0 else 3
                    activity_units.append(weight * variables.x[(activity_id, week, night, eclo)])
        target_units += 2 * activity.total_accesses
        # Rule ``workload``: full workload in half-units, ECLO yields 3.
        if activity_units:
            model.Add(sum(activity_units) >= 2 * activity.total_accesses)
        else:
            model.Add(0 >= 2 * activity.total_accesses)
        total_units.extend(activity_units)

    # Avoid gratuitous overshoot with a tiny tie-break cost.
    model.Add(variables.overshoot == sum(total_units) - target_units)

    for activity_id in variables.activity_order:
        weeks = variables.activity_weeks[activity_id]
        if not weeks:
            continue
        model.AddMaxEquality(
            variables.last_week[activity_id],
            [week * variables.week_present[(activity_id, week)] for week in weeks],
        )
        model.AddMinEquality(
            variables.first_week[activity_id],
            [
                week
                + variables.total_weeks
                * (1 - variables.week_present[(activity_id, week)])
                for week in weeks
            ],
        )

    # Rule ``predecessor``: successor first week strictly after predecessor last.
    for activity_id in variables.activity_order:
        predecessor = compiled.activities[activity_id].predecessor_activity_id
        if predecessor is None or predecessor not in variables.activity_weeks:
            continue
        for week in variables.activity_weeks[activity_id]:
            model.Add(
                variables.week_present[(activity_id, week)]
                + variables.present_at_or_after[(predecessor, week)]
                <= 1
            )


def add_caps_constraints(
    model: Any, compiled: CompiledInstance, variables: SolverVariables
) -> None:
    """Rules ``allocation`` (distinct nights) and ``workfront``."""

    activities_by_contract: dict[str, list[str]] = {}
    for activity_id in variables.activity_order:
        contract = compiled.activities[activity_id].contract_number
        activities_by_contract.setdefault(contract, []).append(activity_id)

    for (contract, week, night), used in variables.used_night.items():
        terms = [
            variables.present[(activity_id, week, night)]
            for activity_id in activities_by_contract.get(contract, [])
            if (activity_id, week, night) in variables.present
        ]
        if terms:
            for term in terms:
                model.Add(used >= term)
            model.Add(used <= sum(terms))
        else:
            model.Add(used == 0)

    for contract, week in sorted(
        {(contract, week) for contract, week, _ in variables.used_night}
    ):
        cap = compiled.contract_weekly_caps[contract]
        model.Add(
            sum(
                variables.used_night[(contract, week, night)]
                for night in variables.physical_nights
            )
            <= cap
        )
        workfronts = compiled.contract_workfronts[contract]
        participants = activities_by_contract.get(contract, [])
        for night in variables.physical_nights:
            terms = [
                variables.present[(activity_id, week, night)]
                for activity_id in participants
                if (activity_id, week, night) in variables.present
            ]
            if terms:
                model.Add(sum(terms) <= workfronts)


def add_possession_constraints(
    model: Any, compiled: CompiledInstance, variables: SolverVariables
) -> None:
    """Rule ``mix`` per possession slot and rules ``closure``/``mirror``/``interchange``.

    A physical night at a location-week is one possession slot. The slot
    indicator is linked exactly to route occupant presence and the activities in
    one slot must form a legal mix: one ``PM`` alone, one ``PC`` plus up to three
    ``C``, or up to four ``C``.

    Closure conflicts are evaluated on the same physical night. Two activities
    may share a night only when they can truly co-share (rule 6): compatible
    access types and at least one common occupied route location where the mix
    constraints place them in the same group. A type-compatible pair with
    disjoint occupied routes still interacts through a buffer and is separated.
    """

    possession = compiled.physical_possession
    for location_id, occupants in sorted(possession.location_occupants.items()):
        for week in variables.weeks:
            for night in variables.physical_nights:
                used = variables.location_slot_used[(location_id, week, night)]
                by_type: dict[str, list[Any]] = {"PM": [], "PC": [], "C": []}
                for activity_id in occupants:
                    key = (activity_id, week, night)
                    if key in variables.present:
                        access_type = compiled.activities[activity_id].access_type
                        by_type.setdefault(access_type, []).append(variables.present[key])
                terms = [term for group in by_type.values() for term in group]
                if terms:
                    for term in terms:
                        model.Add(used >= term)
                    model.Add(used <= sum(terms))
                else:
                    model.Add(used == 0)

                pm = sum(by_type.get("PM", []))
                pc = sum(by_type.get("PC", []))
                coworker = sum(by_type.get("C", []))
                # One PM alone, or one PC plus up to three C, or up to four C.
                model.Add(pm <= 1)
                model.Add(pm + pc <= 1)
                model.Add(C_ONLY_LIMIT * pm + coworker <= C_ONLY_LIMIT)
                model.Add(coworker <= C_ONLY_LIMIT)
                model.Add(
                    C_ONLY_LIMIT * pc + coworker
                    <= C_ONLY_LIMIT + PC_COWORKER_LIMIT
                )

    for left_id, right_id in sorted(possession.closure_conflicts):
        if truly_co_sharable(compiled, left_id, right_id):
            continue
        common_weeks = sorted(
            set(variables.activity_weeks[left_id])
            & set(variables.activity_weeks[right_id])
        )
        for week in common_weeks:
            for night in variables.physical_nights:
                left_key = (left_id, week, night)
                right_key = (right_id, week, night)
                if left_key not in variables.present or right_key not in variables.present:
                    continue
                # No shared physical night unless the pair can truly co-share.
                model.Add(variables.present[left_key] + variables.present[right_key] <= 1)


def add_capacity_constraints(
    model: Any,
    compiled: CompiledInstance,
    variables: SolverVariables,
    policy: ScenarioPolicy,
) -> None:
    """Rule ``capacity`` and the Scenario A/B/C excess semantics.

    Capacity is the number of used physical possession slots at a location-week.
    Each used slot is one legal possession (see :func:`add_possession_constraints`),
    so the count is exact rather than an independent packing bound. ``location_occupants``
    comes from the compiled physical-possession contract, so buffer-only closure
    locations never consume capacity.
    """

    for location_id in sorted(compiled.physical_possession.location_occupants):
        capacity = compiled.location_capacities[location_id]
        for week in variables.weeks:
            slots = [
                variables.location_slot_used[(location_id, week, night)]
                for night in variables.physical_nights
            ]
            model.Add(variables.position[(location_id, week)] == sum(slots))

            hard_limit = policy.hard_capacity_limit(capacity)
            if hard_limit is not None:
                model.Add(variables.position[(location_id, week)] <= hard_limit)
            if (location_id, week) in variables.excess:
                model.Add(
                    variables.excess[(location_id, week)]
                    >= variables.position[(location_id, week)] - capacity
                )


def add_completion_constraints(
    model: Any, compiled: CompiledInstance, variables: SolverVariables, policy: ScenarioPolicy
) -> None:
    """Contract completion week, weighted overrun and Scenario B deadlines."""

    horizon_start = compiled.instance.horizon_start
    for contract_number in variables.completion_week:
        contract = compiled.instance.contracts[contract_number]
        activities = compiled.activities_for_contract(contract_number)
        model.AddMaxEquality(
            variables.completion_week[contract_number],
            [variables.last_week[activity.activity_id] for activity in activities],
        )
        if policy.planned_completion_hard:
            # Date-exact: week_end(w) = horizon_start + 7*(w-1) + 6 must be
            # <= planned_completion_date, i.e. w <= ((delta_days + 1) // 7).
            # A week-based bound would be wrong for non-Sunday planned dates.
            delta_days = (contract.planned_completion_date - horizon_start).days
            max_week = (delta_days + 1) // 7
            model.Add(variables.completion_week[contract_number] <= max_week)

    for activity_id, activity_overrun in variables.activity_overrun.items():
        contract = compiled.instance.contracts[
            compiled.activities[activity_id].contract_number
        ]
        delta = (horizon_start - contract.planned_completion_date).days + 6
        model.Add(
            activity_overrun
            >= 7 * variables.last_week[activity_id] + (delta - 7)
        )


def add_eclo_constraints(
    model: Any, compiled: CompiledInstance, variables: SolverVariables, policy: ScenarioPolicy
) -> None:
    """Rule ``eclo`` and the Scenario C two-week continuity window."""

    if policy.eclo_allowed is False:
        for key, variable in variables.x.items():
            if key[3] == 1:
                model.Add(variable == 0)
        return

    if policy.eclo_window != "two_week_per_line":
        return

    for line_code in sorted(compiled.instance.lines):
        model.Add(sum(variables.eclo_window[(line_code, week)] for week in variables.weeks) <= 1)

    for activity_id in variables.activity_order:
        lines = _affected_lines(compiled, activity_id)
        for week in variables.activity_weeks[activity_id]:
            for night in variables.activity_nights[activity_id]:
                key = (activity_id, week, night, 1)
                if key not in variables.x:
                    continue
                if not lines:
                    model.Add(variables.x[key] == 0)
                    continue
                # A cross-line Live ECLO must fit every affected line's window.
                for line_code in lines:
                    windows = [
                        variables.eclo_window[(line_code, start)]
                        for start in (week - 1, week)
                        if (line_code, start) in variables.eclo_window
                    ]
                    if windows:
                        model.Add(variables.x[key] <= sum(windows))
                    else:
                        model.Add(variables.x[key] == 0)


__all__ = [
    "add_caps_constraints",
    "add_capacity_constraints",
    "add_completion_constraints",
    "add_eclo_constraints",
    "add_linking_constraints",
    "add_possession_constraints",
    "add_time_constraints",
]
