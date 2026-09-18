"""Compiler-facing route expansion helpers (F-INSTANCE-003)."""

from __future__ import annotations

from app.domain.rail.instance_model import PlanningInstance
from app.domain.rail.routes import Route, RouteError, RouteNetwork, expand_route


def expand_all_routes(instance: PlanningInstance) -> dict[str, Route]:
    """Expand every activity route, keyed by activity id in ascending order."""

    network = instance.route_network()
    routes: dict[str, Route] = {}
    for activity_id in sorted(instance.activities):
        activity = instance.activities[activity_id]
        routes[activity_id] = expand_route(
            activity.activity_id,
            activity.start_location_id,
            activity.end_location_id,
            network,
        )
    return routes


__all__ = [
    "Route",
    "RouteError",
    "RouteNetwork",
    "expand_all_routes",
    "expand_route",
]
