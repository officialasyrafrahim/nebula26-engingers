"""Scenario-independent compiled rail instance.

``CompiledInstance`` joins the canonical :class:`PlanningInstance` with the
derived facts the solver needs: expanded routes, buffer closures, opposite-bound
mirroring, H01-H02 interchange effects, predecessor links and the
allocation/workfront metadata. Nothing here depends on Scenario A/B/C; scenario
policy is applied later by ``modules.compiler.policy``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict

from app.domain.rail.instance_model import PlanningInstance
from app.domain.rail.routes import Route


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
    location_capacities: Mapping[str, int]
    contract_weekly_caps: Mapping[str, int]
    contract_workfronts: Mapping[str, int]

    def compiled_activity(self, activity_id: str) -> CompiledActivity:
        return self.activities[activity_id]

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
