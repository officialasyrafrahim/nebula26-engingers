"""Scenario-independent compiled rail instance.

``CompiledInstance`` joins the canonical :class:`PlanningInstance` with the
derived facts the solver needs: expanded routes, buffer closures, opposite-bound
mirroring, H01-H02 interchange effects, predecessor links and the
allocation/workfront metadata. Nothing here depends on Scenario A/B/C; scenario
policy is applied later by ``modules.compiler.policy``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.rail.instance_model import PlanningInstance
from app.domain.rail.routes import Route


def ordered_pair(left: str, right: str) -> tuple[str, str]:
    """Canonical unordered key for a pair of natural ids."""

    return (left, right) if left <= right else (right, left)


class AccessNightDomain(BaseModel):
    """The local ``access_night`` namespace for one contract/type/week.

    PS1 defines ``access_night`` as a per-contract, per-activity-type accounting
    index in ``1..number_of_maximum_access_per_week``. It is deliberately not a
    global physical-night key: two contracts' night ``1`` values are unrelated,
    and a co-share group may span different local values (design A-1/A-3). This
    record keeps that locality explicit so no consumer is tempted to compare
    night numbers across contracts.
    """

    model_config = ConfigDict(frozen=True)

    contract_number: str
    activity_type: str
    week: int
    weekly_cap: int

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.contract_number, self.activity_type, self.week)

    @property
    def nights(self) -> tuple[int, ...]:
        return tuple(range(1, self.weekly_cap + 1))


class ClosureConflict(BaseModel):
    """Two activities whose compiled closures intersect at one or more locations.

    This is a pure compiled fact: it records the shared closed locations and the
    most specific rule tag. Whether the pair may still be simultaneous depends on
    the co-share waiver and is decided by the consumer, not stored here.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    locations: frozenset[str]
    rule: Literal["closure", "mirror", "interchange"]

    @property
    def is_interchange(self) -> bool:
        return self.rule == "interchange"


class PhysicalPossessionContract(BaseModel):
    """Explicit physical possession-slot semantics for the compiled instance.

    The published submission schema only exposes a contract/type-local
    ``access_night``, so a unique physical-night mapping is not derivable from a
    plan (design A-1/A-2/A-3). This contract therefore represents admissibility
    rather than a night map:

    * ``access_night_domains`` keeps the local night namespace per
      ``(contract_number, activity_type, week)``;
    * ``closure_conflicts`` is the graph of activity pairs whose closures
      intersect, with shared locations and a rule tag;
    * ``location_occupants`` lists, per location, the activities whose route
      consumes its capacity (buffer-only closure locations are excluded);
    * ``co_share_allowed`` fixes which access-type pairs are buffer-free.

    A possession is scoped to ``(location_id, week, co_share_group)``. It may
    span several local ``access_night`` values, and capacity counts possessions,
    not nights. Mix legality and packing live in ``modules.compiler.mixes``.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    access_night_domains: Mapping[tuple[str, str, int], AccessNightDomain]
    closure_conflicts: Mapping[tuple[str, str], ClosureConflict]
    location_occupants: Mapping[str, tuple[str, ...]]
    co_share_allowed: Mapping[tuple[str, str], bool]

    def access_night_domain(
        self, contract_number: str, activity_type: str, week: int
    ) -> AccessNightDomain:
        """Return the local night domain, raising ``KeyError`` when unknown."""

        try:
            return self.access_night_domains[(contract_number, activity_type, week)]
        except KeyError:
            raise KeyError(
                f"no access-night domain for ({contract_number!r}, {activity_type!r}, week {week})"
            ) from None

    def occupants_at(self, location_id: str) -> tuple[str, ...]:
        """Activities whose route consumes ``location_id`` (deterministic order)."""

        return self.location_occupants.get(location_id, ())

    def closure_conflict(self, left_id: str, right_id: str) -> ClosureConflict | None:
        """The compiled closure conflict for an activity pair, if any."""

        return self.closure_conflicts.get(ordered_pair(left_id, right_id))

    def co_share_compatible(self, left_type: str, right_type: str) -> bool:
        """Whether two access types may share one possession without a buffer."""

        return bool(self.co_share_allowed.get(tuple(sorted((left_type, right_type))), False))


class CompiledActivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity_id: str
    contract_number: str
    access_type: str
    nature_of_activity: str
    buffer_sectors: int
    opposite_bound_required: bool
    route: Route
    occupied_locations: tuple[str, ...]
    closure_locations: tuple[str, ...]
    closure_sector_ids: tuple[str, ...]
    mirrored_locations: tuple[str, ...]
    interchange_locations: tuple[str, ...]
    closed_locations: tuple[str, ...]
    planned_start_week: int
    total_accesses: int
    weekly_cap: int
    workfronts: int
    predecessor_activity_id: str | None = None
    successor_activity_ids: tuple[str, ...] = ()

    @property
    def affected_locations(self) -> frozenset[str]:
        """Locations whose capacity this activity consumes (its own route)."""

        return frozenset(self.occupied_locations)

    @property
    def exclusion_locations(self) -> frozenset[str]:
        """Locations no other non-co-shared possession may enter."""

        return frozenset(self.closed_locations)


class CompiledInstance(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    instance: PlanningInstance
    activities: Mapping[str, CompiledActivity]
    co_share_allowed: Mapping[tuple[str, str], bool]
    physical_possession: PhysicalPossessionContract
    location_capacities: Mapping[str, int]
    contract_weekly_caps: Mapping[str, int]
    contract_workfronts: Mapping[str, int]

    def compiled_activity(self, activity_id: str) -> CompiledActivity:
        return self.activities[activity_id]

    def access_night_domain(
        self, contract_number: str, activity_type: str, week: int
    ) -> AccessNightDomain:
        """Local ``access_night`` namespace; never a cross-contract night key."""

        return self.physical_possession.access_night_domain(contract_number, activity_type, week)

    def closure_conflict(self, left_id: str, right_id: str) -> ClosureConflict | None:
        """Compiled closure conflict between two activities, if any."""

        return self.physical_possession.closure_conflict(left_id, right_id)

    def activities_for_contract(self, contract_number: str) -> tuple[CompiledActivity, ...]:
        return tuple(
            activity
            for activity_id, activity in sorted(self.activities.items())
            if activity.contract_number == contract_number
        )

    def locations_for(self, activity_ids: Iterable[str]) -> frozenset[str]:
        return frozenset(
            location_id
            for activity_id in activity_ids
            for location_id in self.activities[activity_id].occupied_locations
        )
