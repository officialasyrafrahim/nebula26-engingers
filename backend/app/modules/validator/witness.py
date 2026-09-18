"""Independent physical schedule witness check (F-VALIDATOR-005).

The exported schedule cannot uniquely reconstruct physical simultaneity from
``access_night`` and ``co_share_group`` alone (design Section 9.1). The solver
therefore persists an internal ``physical_night`` witness per access. This module
re-checks a solved schedule directly against that witness using only the compiled
instance, the scenario policy and the rows. It never imports a solver module, so a
solver regression cannot make its own output pass by construction.

The five checks are reported independently, and ``passed`` is the conjunction of
all of them. ``witness_available`` fails closed on witness-free input so a plan
missing physical slots can never silently pass.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.rail.compiled import CompiledInstance
from app.modules.compiler.mixes import legal_access_mix
from app.modules.compiler.policy import ScenarioPolicy

_RULE_STRENGTH = {"interchange": 3, "mirror": 2, "closure": 1}


class PhysicalCheck(BaseModel):
    """One independently reported physical witness check."""

    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class PhysicalWitnessReport(BaseModel):
    """The result of the physical witness check over one solved schedule."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    checks: list[PhysicalCheck] = Field(default_factory=list)


def _field(row: Any, name: str, index: int) -> Any:
    """Read one column from an object, mapping or positional row."""

    if isinstance(row, Mapping):
        return row.get(name)
    if isinstance(row, (tuple, list)):
        return row[index] if len(row) > index else None
    return getattr(row, name, None)


@dataclass(frozen=True)
class _WitnessIndex:
    """Everything the checks need, derived only from the witness rows."""

    slots_by_activity_week: dict[tuple[str, int], set[int]]
    locations_by_activity_week: dict[tuple[str, int], set[str]]
    groups: dict[tuple[str, int, str], str | None]
    present: dict[tuple[str, int, int], set[str]]
    occupants: dict[tuple[str, int], set[str]]
    slots_by_location_week: dict[tuple[str, int], set[int]]
    access_rows: int
    missing_rows: int
    missing_activities: set[str]


def _index(access_rows: Sequence[Any], occupancy_rows: Sequence[Any]) -> _WitnessIndex:
    """Join the witness access slots with the submitted occupancy rows."""

    slots_by_activity_week: dict[tuple[str, int], set[int]] = defaultdict(set)
    missing_activities: set[str] = set()
    access_count = 0
    missing_count = 0

    for row in access_rows:
        access_count += 1
        activity_id = _field(row, "activity_id", 0)
        week = _field(row, "week", 1)
        physical_night = _field(row, "physical_night", 2)
        if activity_id is None or week is None:
            continue
        if physical_night is None:
            missing_count += 1
            missing_activities.add(str(activity_id))
            continue
        slots_by_activity_week[(str(activity_id), int(week))].add(int(physical_night))

    locations_by_activity_week: dict[tuple[str, int], set[str]] = defaultdict(set)
    groups: dict[tuple[str, int, str], str | None] = {}
    present: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    occupants: dict[tuple[str, int], set[str]] = defaultdict(set)
    slots_by_location_week: dict[tuple[str, int], set[int]] = defaultdict(set)

    for row in occupancy_rows:
        activity_id = _field(row, "activity_id", 0)
        week = _field(row, "week", 1)
        location_id = _field(row, "location_id", 2)
        co_share_group = _field(row, "co_share_group", 3)
        if activity_id is None or week is None or location_id is None:
            continue
        activity_id = str(activity_id)
        week = int(week)
        location_id = str(location_id)
        locations_by_activity_week[(activity_id, week)].add(location_id)
        groups[(activity_id, week, location_id)] = co_share_group
        occupants[(location_id, week)].add(activity_id)
        for night in slots_by_activity_week.get((activity_id, week), ()):
            present[(location_id, week, night)].add(activity_id)
            slots_by_location_week[(location_id, week)].add(night)

    return _WitnessIndex(
        slots_by_activity_week=dict(slots_by_activity_week),
        locations_by_activity_week=dict(locations_by_activity_week),
        groups=groups,
        present=dict(present),
        occupants=dict(occupants),
        slots_by_location_week=dict(slots_by_location_week),
        access_rows=access_count,
        missing_rows=missing_count,
        missing_activities=missing_activities,
    )


def _slot_mix(compiled: CompiledInstance, index: _WitnessIndex) -> PhysicalCheck:
    """Every ``(location, week, physical slot)`` holds one legal possession."""

    violations: list[dict[str, Any]] = []
    for (location_id, week, night), activities in sorted(index.present.items()):
        known = sorted(a for a in activities if a in compiled.activities)
        if not known:
            continue
        types = [compiled.activities[a].access_type for a in known]
        if not legal_access_mix(types):
            violations.append(
                {
                    "location_id": location_id,
                    "week": week,
                    "physical_night": night,
                    "access_types": types,
                    "activities": known,
                }
            )
    return PhysicalCheck(
        name="slot_mix",
        passed=not violations,
        detail={
            "slots_checked": len(index.present),
            "violations": violations,
        },
    )


def _waived_by_shared_possession(
    index: _WitnessIndex, left: str, right: str, week: int
) -> bool:
    """Whether a pair shares one submitted group at a common occupied location."""

    common = index.locations_by_activity_week.get(
        (left, week), set()
    ) & index.locations_by_activity_week.get((right, week), set())
    for location_id in common:
        left_group = index.groups.get((left, week, location_id))
        right_group = index.groups.get((right, week, location_id))
        if left_group is not None and left_group == right_group:
            return True
    return False


def _closure_simultaneity(
    compiled: CompiledInstance, index: _WitnessIndex
) -> PhysicalCheck:
    """Compiled closure pairs must not share a physical slot unless co-shared."""

    conflicts = compiled.physical_possession.closure_conflicts
    weeks_by_activity: dict[str, set[int]] = defaultdict(set)
    for activity_id, week in index.slots_by_activity_week:
        weeks_by_activity[activity_id].add(week)

    violations: list[dict[str, Any]] = []
    strongest = 0
    strongest_rule: str | None = None

    for (left, right), conflict in sorted(conflicts.items()):
        common_weeks = weeks_by_activity.get(left, set()) & weeks_by_activity.get(
            right, set()
        )
        for week in sorted(common_weeks):
            shared = index.slots_by_activity_week.get(
                (left, week), set()
            ) & index.slots_by_activity_week.get((right, week), set())
            if not shared:
                continue
            if _waived_by_shared_possession(index, left, right, week):
                continue
            violations.append(
                {
                    "left": left,
                    "right": right,
                    "week": week,
                    "physical_nights": sorted(shared),
                    "rule": conflict.rule,
                }
            )
            strength = _RULE_STRENGTH.get(conflict.rule, 0)
            if strength > strongest:
                strongest = strength
                strongest_rule = conflict.rule

    return PhysicalCheck(
        name="closure_simultaneity",
        passed=not violations,
        detail={
            "pairs_checked": len(conflicts),
            "violations": violations,
            "strongest_rule": strongest_rule,
        },
    )


def _capacity_slots(
    compiled: CompiledInstance, policy: ScenarioPolicy, index: _WitnessIndex
) -> PhysicalCheck:
    """Distinct occupied physical slots per location-week against policy."""

    hard_violations: list[dict[str, Any]] = []
    soft_excess: list[dict[str, Any]] = []
    soft_total = 0

    for (location_id, week), nights in sorted(index.slots_by_location_week.items()):
        supply = int(compiled.location_capacities.get(location_id, 0))
        used = len(nights)
        limit = policy.hard_capacity_limit(supply)
        if limit is not None and used > limit:
            hard_violations.append(
                {
                    "location_id": location_id,
                    "week": week,
                    "used_slots": used,
                    "hard_limit": limit,
                    "supply_capacity": supply,
                }
            )
        excess = max(0, used - supply)
        if excess:
            soft_excess.append(
                {
                    "location_id": location_id,
                    "week": week,
                    "used_slots": used,
                    "supply_capacity": supply,
                    "excess": excess,
                }
            )
            soft_total += excess

    return PhysicalCheck(
        name="capacity_slots",
        passed=not hard_violations,
        detail={
            "location_weeks_checked": len(index.slots_by_location_week),
            "hard_violations": hard_violations,
            "soft_excess": soft_excess,
            "soft_excess_total": soft_total,
        },
    )


def _workfront_slots(compiled: CompiledInstance, index: _WitnessIndex) -> PhysicalCheck:
    """Concurrent contract activities per physical slot against workfront caps."""

    counts: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for (activity_id, week), nights in index.slots_by_activity_week.items():
        activity = compiled.activities.get(activity_id)
        if activity is None:
            continue
        for night in nights:
            counts[(activity.contract_number, week, night)].add(activity_id)

    violations: list[dict[str, Any]] = []
    for (contract_number, week, night), activities in sorted(counts.items()):
        cap = compiled.contract_workfronts.get(contract_number)
        if cap is None:
            continue
        if len(activities) > cap:
            violations.append(
                {
                    "contract_number": contract_number,
                    "week": week,
                    "physical_night": night,
                    "concurrent_activities": len(activities),
                    "workfront_cap": cap,
                    "activities": sorted(activities),
                }
            )

    return PhysicalCheck(
        name="workfront_slots",
        passed=not violations,
        detail={
            "contract_week_slots_checked": len(counts),
            "violations": violations,
        },
    )


def _witness_available(index: _WitnessIndex) -> PhysicalCheck:
    """Fail closed when any access row carries no physical slot witness."""

    detail: dict[str, Any] = {
        "access_rows": index.access_rows,
        "rows_without_physical_night": index.missing_rows,
        "activities_without_physical_night": sorted(index.missing_activities),
    }
    if index.access_rows == 0:
        detail["reason"] = "no access rows to witness"
        return PhysicalCheck(name="witness_available", passed=False, detail=detail)
    if index.missing_rows:
        detail["reason"] = "some access rows carry no physical_night witness"
        return PhysicalCheck(name="witness_available", passed=False, detail=detail)
    return PhysicalCheck(name="witness_available", passed=True, detail=detail)


def check_physical_witness(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    access_rows: Sequence[Any],
    occupancy_rows: Sequence[Any],
) -> PhysicalWitnessReport:
    """Check the solver's persisted physical slots for hard physical conflicts.

    ``access_rows`` provide ``(activity_id, week, physical_night)`` and
    ``occupancy_rows`` provide ``(activity_id, week, location_id, co_share_group)``.
    Objects, mappings and positional tuples are all accepted. Every check is
    reported independently and the report passes only when all of them pass.
    """

    index = _index(access_rows, occupancy_rows)
    checks = [
        _slot_mix(compiled, index),
        _closure_simultaneity(compiled, index),
        _capacity_slots(compiled, policy, index),
        _workfront_slots(compiled, index),
        _witness_available(index),
    ]
    return PhysicalWitnessReport(
        passed=all(check.passed for check in checks),
        checks=checks,
    )


__all__ = [
    "PhysicalCheck",
    "PhysicalWitnessReport",
    "check_physical_witness",
]
