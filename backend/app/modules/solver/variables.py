"""Decision-variable construction for the rail CP-SAT model.

Only creation lives here; linking constraints live in :mod:`constraints`. The
container keeps the per-activity week/night/eclo domains so downstream code can
iterate the exact same keys the model used. All iteration follows a
deterministic order (contract priority, activity priority, activity id) so a
fixed seed reproduces the same variable indices run to run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.rail.compiled import CompiledInstance
from app.modules.compiler.policy import ScenarioPolicy

PHYSICAL_NIGHTS_PER_WEEK = 7


@dataclass(slots=True)
class SolverVariables:
    """Every CP variable the model creates, keyed by natural ids."""

    total_weeks: int
    weeks: tuple[int, ...]
    physical_nights: tuple[int, ...]
    activity_order: tuple[str, ...]
    activity_weeks: dict[str, tuple[int, ...]]
    activity_nights: dict[str, tuple[int, ...]]
    eclo_values: tuple[int, ...]
    x: dict[tuple[str, int, int, int], Any]
    present: dict[tuple[str, int, int], Any]
    week_present: dict[tuple[str, int], Any]
    present_at_or_after: dict[tuple[str, int], Any]
    first_week: dict[str, Any]
    last_week: dict[str, Any]
    used_night: dict[tuple[str, int, int], Any]
    location_slot_used: dict[tuple[str, int, int], Any]
    position: dict[tuple[str, int], Any]
    excess: dict[tuple[str, int], Any]
    completion_week: dict[str, Any]
    activity_overrun: dict[str, Any]
    overshoot: Any
    eclo_window: dict[tuple[str, int], Any]


def ordered_activity_ids(compiled: CompiledInstance) -> tuple[str, ...]:
    """Deterministic activity order used for variable creation."""

    instance = compiled.instance

    def sort_key(activity_id: str) -> tuple[int, int, str]:
        activity = instance.activities[activity_id]
        return (
            instance.contracts[activity.contract_number].contract_priority,
            activity.activity_priority,
            activity_id,
        )

    return tuple(sorted(compiled.activities, key=sort_key))


def max_nights(compiled: CompiledInstance) -> int:
    caps = [
        compiled.contract_weekly_caps[activity.contract_number]
        for activity in compiled.activities.values()
    ]
    return max(caps, default=1)


def physical_night_count(compiled: CompiledInstance) -> int:
    """Number of distinct physical nights the model may assign in a week.

    A week has seven calendar nights. The domain is widened when a published
    contract cap or location supply exceeds seven, so the local ``access_night``
    range (``1..cap``) is always representable after ranking.
    """

    total = PHYSICAL_NIGHTS_PER_WEEK
    for cap in compiled.contract_weekly_caps.values():
        total = max(total, cap)
    for capacity in compiled.location_capacities.values():
        total = max(total, capacity)
    return max(1, total)


def physical_nights(compiled: CompiledInstance) -> tuple[int, ...]:
    return tuple(range(1, physical_night_count(compiled) + 1))


def occupied_location_ids(compiled: CompiledInstance) -> tuple[str, ...]:
    locations = {
        location_id
        for activity in compiled.activities.values()
        for location_id in activity.occupied_locations
    }
    return tuple(sorted(locations))


def _overrun_upper_bound(compiled: CompiledInstance, total_weeks: int) -> dict[str, int]:
    horizon_start = compiled.instance.horizon_start
    bounds: dict[str, int] = {}
    for contract_number, contract in compiled.instance.contracts.items():
        delta = (horizon_start - contract.planned_completion_date).days + 6
        c0 = delta - 7
        bounds[contract_number] = max(0, 7 * total_weeks + c0)
    return bounds


def build_variables(
    model: Any,
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    total_weeks: int,
) -> SolverVariables:
    """Create every decision variable for one scenario."""

    instance = compiled.instance
    weeks = tuple(range(1, total_weeks + 1))
    nights = physical_nights(compiled)
    activity_order = ordered_activity_ids(compiled)
    eclo_values = (0, 1) if policy.eclo_allowed else (0,)

    activity_weeks: dict[str, tuple[int, ...]] = {}
    activity_nights: dict[str, tuple[int, ...]] = {}
    x: dict[tuple[str, int, int, int], Any] = {}
    present: dict[tuple[str, int, int], Any] = {}
    week_present: dict[tuple[str, int], Any] = {}
    present_at_or_after: dict[tuple[str, int], Any] = {}
    first_week: dict[str, Any] = {}
    last_week: dict[str, Any] = {}

    for activity_id in activity_order:
        activity = compiled.activities[activity_id]
        start = max(1, activity.planned_start_week)
        weeks_a = tuple(week for week in range(start, total_weeks + 1))
        nights_a = nights
        activity_weeks[activity_id] = weeks_a
        activity_nights[activity_id] = nights_a
        for week in weeks_a:
            for night in nights_a:
                for eclo in eclo_values:
                    x[(activity_id, week, night, eclo)] = model.NewBoolVar(
                        f"x_{activity_id}_w{week}_n{night}_e{eclo}"
                    )
                present[(activity_id, week, night)] = model.NewBoolVar(
                    f"present_{activity_id}_w{week}_n{night}"
                )
            week_present[(activity_id, week)] = model.NewBoolVar(
                f"week_present_{activity_id}_w{week}"
            )
        first_week[activity_id] = model.NewIntVar(
            1, total_weeks + 1, f"first_week_{activity_id}"
        )
        last_week[activity_id] = model.NewIntVar(0, total_weeks, f"last_week_{activity_id}")
        for week in range(total_weeks, 0, -1):
            present_at_or_after[(activity_id, week)] = model.NewBoolVar(
                f"present_at_or_after_{activity_id}_w{week}"
            )

    used_night: dict[tuple[str, int, int], Any] = {}
    for contract_number in sorted(compiled.contract_weekly_caps):
        for week in weeks:
            for night in nights:
                used_night[(contract_number, week, night)] = model.NewBoolVar(
                    f"night_used_{contract_number}_w{week}_n{night}"
                )

    # Capacity is counted in physical possession slots. One physical night at a
    # location-week is one possession, so the slot count is bounded by both the
    # number of route occupants and the number of physical nights.
    locations = occupied_location_ids(compiled)
    location_activity_count: dict[str, int] = {}
    for activity in compiled.activities.values():
        for location_id in activity.occupied_locations:
            location_activity_count[location_id] = (
                location_activity_count.get(location_id, 0) + 1
            )
    location_slot_used: dict[tuple[str, int, int], Any] = {}
    position: dict[tuple[str, int], Any] = {}
    excess: dict[tuple[str, int], Any] = {}
    for location_id in locations:
        bound = max(1, min(location_activity_count.get(location_id, 1), len(nights)))
        for week in weeks:
            position[(location_id, week)] = model.NewIntVar(
                0, bound, f"position_{location_id}_w{week}"
            )
            if policy.excess_access_nights_scored:
                excess[(location_id, week)] = model.NewIntVar(
                    0, bound, f"excess_{location_id}_w{week}"
                )
            for night in nights:
                location_slot_used[(location_id, week, night)] = model.NewBoolVar(
                    f"slot_used_{location_id}_w{week}_n{night}"
                )

    bounds = _overrun_upper_bound(compiled, total_weeks)
    completion_week: dict[str, Any] = {}
    for contract_number in sorted(instance.contracts):
        if not compiled.activities_for_contract(contract_number):
            continue
        completion_week[contract_number] = model.NewIntVar(
            1, total_weeks, f"completion_{contract_number}"
        )

    activity_overrun: dict[str, Any] = {}
    for activity_id in activity_order:
        contract_number = compiled.activities[activity_id].contract_number
        activity_overrun[activity_id] = model.NewIntVar(
            0, bounds[contract_number], f"activity_overrun_{activity_id}"
        )

    max_half_units = sum(
        3 * len(activity_weeks[activity_id]) for activity_id in activity_order
    )
    overshoot = model.NewIntVar(0, max(max_half_units, 0), "overshoot")

    eclo_window: dict[tuple[str, int], Any] = {}
    if policy.eclo_window == "two_week_per_line":
        for line_code in sorted(instance.lines):
            for start in weeks:
                eclo_window[(line_code, start)] = model.NewBoolVar(
                    f"eclo_window_{line_code}_{start}"
                )

    return SolverVariables(
        total_weeks=total_weeks,
        weeks=weeks,
        physical_nights=nights,
        activity_order=activity_order,
        activity_weeks=activity_weeks,
        activity_nights=activity_nights,
        eclo_values=eclo_values,
        x=x,
        present=present,
        week_present=week_present,
        present_at_or_after=present_at_or_after,
        first_week=first_week,
        last_week=last_week,
        used_night=used_night,
        location_slot_used=location_slot_used,
        position=position,
        excess=excess,
        completion_week=completion_week,
        activity_overrun=activity_overrun,
        overshoot=overshoot,
        eclo_window=eclo_window,
    )


__all__ = [
    "PHYSICAL_NIGHTS_PER_WEEK",
    "SolverVariables",
    "build_variables",
    "max_nights",
    "occupied_location_ids",
    "ordered_activity_ids",
    "physical_night_count",
    "physical_nights",
]
