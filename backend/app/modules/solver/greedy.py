"""Deterministic greedy incumbent builder for the rail CP-SAT model.

Under a tight solve budget CP-SAT can stop at ``UNKNOWN`` with no incumbent even
when a complete schedule exists. This module builds a feasible starting schedule
with a single earliest-fit pass so the engine can hand it to CP-SAT as a
solution hint.

The builder reasons only about real facts:

* activities are placed on the shared physical nights ``1..7``; local
  ``access_night`` values are never compared across contracts;
* a possession is ``(location_id, week, physical_night)`` and must hold a legal
  PM/PC/C mix;
* closure, Live mirroring and interchange conflicts are read from the compiled
  graph and separated on physical nights unless the pair can truly co-share;
* planned start, predecessor finish, weekly caps, workfront caps, location
  capacity and the Scenario B hard completion date are hard limits.

The result is deliberately conservative. When the pass cannot place every access
inside the hard limits it returns ``None`` rather than emitting an unsafe plan,
so the caller can fall back to the normal CP-SAT search. The engine additionally
gates the schedule through the independent physical witness before using it.
"""

from __future__ import annotations

import heapq
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.domain.rail.compiled import CompiledInstance
from app.domain.rail.nights import PHYSICAL_NIGHT_SLOTS
from app.modules.compiler.mixes import legal_access_mix
from app.modules.compiler.policy import ScenarioPolicy
from app.modules.solver.possession import truly_co_sharable


@dataclass(frozen=True)
class GreedyPlacement:
    """One greedily placed access on a global physical night."""

    activity_id: str
    week: int
    physical_night: int
    eclo: bool = False


@dataclass(frozen=True)
class GreedySolution:
    """A complete greedy candidate schedule in deterministic order."""

    placements: tuple[GreedyPlacement, ...]


def _activity_sort_key(compiled: CompiledInstance, activity_id: str) -> tuple[int, int, str]:
    activity = compiled.activities[activity_id]
    contract = compiled.instance.contracts[activity.contract_number]
    source = compiled.instance.activities[activity_id]
    return (contract.contract_priority, source.activity_priority, activity_id)


def _topological_order(compiled: CompiledInstance) -> tuple[str, ...]:
    """Predecessor-respecting order with a deterministic priority tie-break.

    Every activity has at most one predecessor, so a heap of ready activities is
    enough. Ties break on contract priority, activity priority and id, matching
    the solver's own variable order.
    """

    indegree: dict[str, int] = {}
    children: dict[str, list[str]] = defaultdict(list)
    for activity_id in compiled.activities:
        predecessor = compiled.activities[activity_id].predecessor_activity_id
        if predecessor is None or predecessor not in compiled.activities:
            indegree[activity_id] = 0
            continue
        indegree[activity_id] = 1
        children[predecessor].append(activity_id)

    ready: list[tuple[tuple[int, int, str], str]] = []
    for activity_id, degree in indegree.items():
        if degree == 0:
            heapq.heappush(ready, (_activity_sort_key(compiled, activity_id), activity_id))

    order: list[str] = []
    while ready:
        _, activity_id = heapq.heappop(ready)
        order.append(activity_id)
        for child in children.get(activity_id, ()):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, (_activity_sort_key(compiled, child), child))

    # A validated instance has no predecessor cycle. If one slipped through, the
    # remaining activities are appended in priority order so the pass stays total.
    if len(order) < len(compiled.activities):
        placed = set(order)
        for activity_id in sorted(
            compiled.activities, key=lambda aid: _activity_sort_key(compiled, aid)
        ):
            if activity_id not in placed:
                order.append(activity_id)
    return tuple(order)


def _hard_conflict_pairs(compiled: CompiledInstance) -> set[tuple[str, str]]:
    """Closure pairs that must never share a physical night.

    Co-share-compatible pairs with a common occupied location keep their waiver
    and are omitted; every other compiled closure pair is a hard separation.
    """

    pairs: set[tuple[str, str]] = set()
    for (left_id, right_id) in compiled.physical_possession.closure_conflicts:
        if truly_co_sharable(compiled, left_id, right_id):
            continue
        left, right = sorted((left_id, right_id))
        pairs.add((left, right))
    return pairs


def _contract_deadlines(
    compiled: CompiledInstance, policy: ScenarioPolicy
) -> dict[str, int]:
    """Hard completion week per contract for date-exact scenario policies."""

    if not policy.planned_completion_hard:
        return {}
    horizon_start = compiled.instance.horizon_start
    deadlines: dict[str, int] = {}
    for contract_number, contract in compiled.instance.contracts.items():
        delta_days = (contract.planned_completion_date - horizon_start).days
        deadlines[contract_number] = (delta_days + 1) // 7
    return deadlines


class _GreedyState:
    """Mutable placement bookkeeping for one greedy pass."""

    def __init__(self, compiled: CompiledInstance, policy: ScenarioPolicy):
        self.compiled = compiled
        self.policy = policy
        self.hard_pairs = _hard_conflict_pairs(compiled)
        self.deadlines = _contract_deadlines(compiled, policy)
        self.slot_activities: dict[tuple[int, int], set[str]] = defaultdict(set)
        self.slot_types: dict[tuple[str, int, int], Counter[str]] = defaultdict(Counter)
        self.location_week_nights: dict[tuple[str, int], set[int]] = defaultdict(set)
        self.contract_week_nights: dict[tuple[str, int], set[int]] = defaultdict(set)
        self.contract_night_activities: dict[tuple[str, int, int], set[str]] = defaultdict(set)
        self.placements: dict[str, set[tuple[int, int]]] = defaultdict(set)
        self.last_week: dict[str, int] = {}

    def _capacity_limit(self, location_id: str) -> int | None:
        supply = self.compiled.location_capacities.get(location_id, 0)
        return self.policy.hard_capacity_limit(supply)

    def admissible(self, activity_id: str, week: int, night: int) -> bool:
        if any(
            (activity_id, other) in self.hard_pairs
            or (other, activity_id) in self.hard_pairs
            for other in self.slot_activities.get((week, night), ())
        ):
            return False

        activity = self.compiled.activities[activity_id]
        contract = activity.contract_number
        locations = tuple(dict.fromkeys(activity.occupied_locations))

        for location_id in locations:
            used = self.location_week_nights.get((location_id, week), set())
            limit = self._capacity_limit(location_id)
            if limit is not None and night not in used and len(used) >= limit:
                return False

        used_nights = self.contract_week_nights.get((contract, week), set())
        if (
            night not in used_nights
            and len(used_nights) >= self.compiled.contract_weekly_caps[contract]
        ):
            return False

        workfront = self.compiled.contract_workfronts[contract]
        if len(self.contract_night_activities.get((contract, week, night), set())) >= workfront:
            return False

        for location_id in locations:
            types = Counter(self.slot_types.get((location_id, week, night), Counter()))
            types[activity.access_type] += 1
            if not legal_access_mix(types):
                return False
        return True

    def place(self, activity_id: str, week: int, night: int, eclo: bool) -> None:
        activity = self.compiled.activities[activity_id]
        contract = activity.contract_number
        locations = tuple(dict.fromkeys(activity.occupied_locations))

        self.slot_activities[(week, night)].add(activity_id)
        self.placements[activity_id].add((week, night))
        self.last_week[activity_id] = max(self.last_week.get(activity_id, 0), week)

        for location_id in locations:
            self.location_week_nights[(location_id, week)].add(night)
            self.slot_types[(location_id, week, night)][activity.access_type] += 1

        self.contract_week_nights[(contract, week)].add(night)
        self.contract_night_activities[(contract, week, night)].add(activity_id)


def build_greedy_solution(
    compiled: CompiledInstance,
    policy: ScenarioPolicy,
    total_weeks: int,
) -> GreedySolution | None:
    """Build one complete candidate schedule, or ``None`` when none is reachable.

    Activities are visited in predecessor order and each access takes the
    earliest ``(week, physical_night)`` that keeps every hard rule intact. ECLO
    is never used: a plain access contributes the full two half-units the
    workload rule asks for, so no scenario's ECLO window is needed.
    """

    if total_weeks < 1:
        return None
    state = _GreedyState(compiled, policy)
    order = _topological_order(compiled)
    placements: list[GreedyPlacement] = []

    for activity_id in order:
        activity = compiled.activities[activity_id]
        contract = activity.contract_number
        deadline = state.deadlines.get(contract)
        predecessor = activity.predecessor_activity_id
        earliest = max(1, activity.planned_start_week)
        if predecessor is not None and predecessor in state.last_week:
            earliest = max(earliest, state.last_week[predecessor] + 1)

        last_assigned = earliest - 1
        for _ in range(activity.total_accesses):
            placed = False
            week = max(earliest, last_assigned + 1)
            while week <= total_weeks and (deadline is None or week <= deadline):
                for night in PHYSICAL_NIGHT_SLOTS:
                    if state.admissible(activity_id, week, night):
                        state.place(activity_id, week, night, eclo=False)
                        placements.append(
                            GreedyPlacement(
                                activity_id=activity_id,
                                week=week,
                                physical_night=night,
                                eclo=False,
                            )
                        )
                        last_assigned = week
                        placed = True
                        break
                if placed:
                    break
                week += 1
            if not placed:
                return None

    placements.sort(key=lambda item: (item.activity_id, item.week, item.physical_night))
    return GreedySolution(placements=tuple(placements))


__all__ = ["GreedyPlacement", "GreedySolution", "build_greedy_solution"]
