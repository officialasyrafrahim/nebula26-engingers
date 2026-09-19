"""Rule compiler: PlanningInstance -> scenario-independent CompiledInstance."""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.rail.compiled import (
    AccessNightDomain,
    CompiledActivity,
    CompiledInstance,
    PhysicalPossessionContract,
)
from app.domain.rail.instance_model import Activity, PlanningInstance, ordered_activities
from app.domain.rail.routes import Route, expand_route
from app.modules.compiler.closures import (
    LIVE_NATURE,
    buffered_closure,
    build_closure_conflicts,
    ensure_locations_present,
    interchange_locations,
    interchange_triggered,
    mirrored_locations,
)
from app.modules.compiler.mixes import build_co_share_allowed


def compile_activity(
    instance: PlanningInstance,
    activity: Activity,
    route: Route,
) -> CompiledActivity:
    """Compile one activity's route, closures, mirroring and metadata."""

    contract = instance.contracts[activity.contract_number]
    buffer_rule = instance.buffer_rules[contract.nature_of_activity]

    closure = buffered_closure(instance, route, buffer_rule.up_to_buffer_sectors)
    mirrored = (
        mirrored_locations(closure.location_ids)
        if buffer_rule.opposite_bound_required
        else ()
    )
    interchange: tuple[str, ...] = ()
    if contract.nature_of_activity == LIVE_NATURE and interchange_triggered(route, closure):
        interchange = interchange_locations(instance, route.line_code)

    ensure_locations_present(
        instance, closure.location_ids, "buffer closure", activity.activity_id
    )
    ensure_locations_present(
        instance, mirrored, "opposite-bound mirror", activity.activity_id
    )
    ensure_locations_present(
        instance, interchange, "interchange closure", activity.activity_id
    )

    closed_locations = tuple(
        dict.fromkeys(closure.location_ids + mirrored + interchange)
    )

    return CompiledActivity(
        activity_id=activity.activity_id,
        contract_number=contract.contract_number,
        access_type=contract.access_type,
        nature_of_activity=contract.nature_of_activity,
        buffer_sectors=buffer_rule.up_to_buffer_sectors,
        opposite_bound_required=buffer_rule.opposite_bound_required,
        route=route,
        occupied_locations=route.location_ids,
        closure_locations=closure.location_ids,
        closure_sector_ids=closure.sector_ids,
        mirrored_locations=mirrored,
        interchange_locations=interchange,
        closed_locations=closed_locations,
        planned_start_week=instance.planned_start_week(activity),
        total_accesses=activity.total_accesses,
        weekly_cap=contract.number_of_maximum_access_per_week,
        workfronts=contract.number_of_workfronts,
        predecessor_activity_id=activity.predecessor_activity_id,
        successor_activity_ids=instance.successors.get(activity.activity_id, ()),
    )


def build_access_night_domains(
    instance: PlanningInstance,
) -> dict[tuple[str, str, int], AccessNightDomain]:
    """Enumerate the local ``access_night`` domain for every contract-week.

    The key is ``(contract_number, activity_type, week)`` and the value repeats
    ``1..weekly_cap``. This makes the locality explicit: the same numeric night
    in two contracts is two unrelated slots, so consumers never join on it.
    """

    domains: dict[tuple[str, str, int], AccessNightDomain] = {}
    for contract_number, contract in sorted(instance.contracts.items()):
        for week in range(1, instance.horizon_weeks + 1):
            domains[(contract_number, contract.activity_type, week)] = AccessNightDomain(
                contract_number=contract_number,
                activity_type=contract.activity_type,
                week=week,
                weekly_cap=contract.number_of_maximum_access_per_week,
            )
    return domains


def build_location_occupants(
    activities: Mapping[str, CompiledActivity],
) -> dict[str, tuple[str, ...]]:
    """Index route occupants by location in deterministic activity-id order.

    Only occupied route locations count. Buffer, mirror and interchange closure
    locations are intentionally excluded because they never consume capacity.
    """

    occupants: dict[str, list[str]] = {}
    for activity_id in sorted(activities):
        activity = activities[activity_id]
        for location_id in dict.fromkeys(activity.occupied_locations):
            occupants.setdefault(location_id, []).append(activity_id)
    return {location_id: tuple(ids) for location_id, ids in sorted(occupants.items())}


def compile_instance(instance: PlanningInstance) -> CompiledInstance:
    """Compile every activity and attach capacities and compatibility metadata."""

    network = instance.route_network()
    compiled: dict[str, CompiledActivity] = {}
    for activity in ordered_activities(instance.activities):
        route = expand_route(
            activity.activity_id,
            activity.start_location_id,
            activity.end_location_id,
            network,
        )
        compiled[activity.activity_id] = compile_activity(instance, activity, route)

    co_share_allowed = build_co_share_allowed()
    physical_possession = PhysicalPossessionContract(
        access_night_domains=build_access_night_domains(instance),
        closure_conflicts=build_closure_conflicts(compiled),
        location_occupants=build_location_occupants(compiled),
        co_share_allowed=co_share_allowed,
    )

    return CompiledInstance(
        instance=instance,
        activities=compiled,
        co_share_allowed=co_share_allowed,
        physical_possession=physical_possession,
        location_capacities={
            location_id: location.supply_capacity
            for location_id, location in instance.locations.items()
        },
        contract_weekly_caps={
            contract_number: contract.number_of_maximum_access_per_week
            for contract_number, contract in instance.contracts.items()
        },
        contract_workfronts={
            contract_number: contract.number_of_workfronts
            for contract_number, contract in instance.contracts.items()
        },
    )
