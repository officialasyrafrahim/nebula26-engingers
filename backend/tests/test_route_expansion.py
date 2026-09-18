"""Route expansion from book-in to book-out (AT-02, INP-03)."""

from __future__ import annotations

import pytest

from app.domain.rail.routes import RouteError, expand_route
from tests.helpers_rail import (
    load_public_compiled,
    load_public_instance,
    sample_occupancy_locations,
)


def _expand(activity_id: str):
    instance = load_public_instance()
    activity = instance.activities[activity_id]
    return expand_route(
        activity_id,
        activity.start_location_id,
        activity.end_location_id,
        instance.route_network(),
    )


def test_single_sector_route_is_inclusive():
    route = _expand("A013")
    assert route.line_code == "ALP"
    assert route.bound == "WB"
    assert set(route.station_ids) == {"S05", "S06"}
    assert set(route.sector_ids) == {"SEC:ALP:S05_S06"}
    assert route.occupied_location_ids == frozenset(
        {
            "PLAT:ALP:S05:WB",
            "PLAT:ALP:S06:WB",
            "SEC:ALP:S05_S06:WB",
        }
    )


@pytest.mark.parametrize("activity_id", ["A002", "A003", "A006", "A020", "A039"])
def test_multi_sector_routes_are_inclusive(activity_id):
    route = _expand(activity_id)
    assert route.location_ids == tuple(dict.fromkeys(route.location_ids))
    assert route.occupied_location_ids == frozenset(
        sample_occupancy_locations()[activity_id]
    )


def test_every_public_activity_matches_sample_occupancy():
    compiled = load_public_compiled()
    sample = sample_occupancy_locations()
    assert set(compiled.activities) == set(sample)
    for activity_id, activity in compiled.activities.items():
        assert set(activity.occupied_locations) == set(sample[activity_id])


def test_direction_does_not_change_occupied_set():
    forward = _expand("A003")
    instance = load_public_instance()
    activity = instance.activities["A003"]
    reverse = expand_route(
        "A003",
        activity.end_location_id,
        activity.start_location_id,
        instance.route_network(),
    )
    assert reverse.occupied_location_ids == forward.occupied_location_ids


def test_line_mismatch_is_rejected():
    instance = load_public_instance()
    with pytest.raises(RouteError, match="crosses lines"):
        expand_route(
            "X",
            "SEC:ALP:S03_S04:EB",
            "SEC:BET:S12_S13:EB",
            instance.route_network(),
        )


def test_bound_mismatch_is_rejected():
    instance = load_public_instance()
    with pytest.raises(RouteError, match="crosses bounds"):
        expand_route(
            "X",
            "SEC:ALP:S03_S04:EB",
            "SEC:ALP:S04_H01:WB",
            instance.route_network(),
        )


def test_platform_endpoint_is_rejected():
    instance = load_public_instance()
    with pytest.raises(RouteError, match="must be a tunnel sector"):
        expand_route(
            "X",
            "PLAT:ALP:S03:EB",
            "SEC:ALP:S04_H01:EB",
            instance.route_network(),
        )


def test_unknown_sector_is_rejected():
    instance = load_public_instance()
    with pytest.raises(RouteError, match="unknown tunnel sector"):
        expand_route(
            "X",
            "SEC:ALP:S99_S100:EB",
            "SEC:ALP:S04_H01:EB",
            instance.route_network(),
        )


def test_sector_gap_is_rejected():
    instance = load_public_instance()
    network = instance.route_network()
    gapped = network.model_copy(
        update={
            "sectors": {
                sector_id: sector
                for sector_id, sector in network.sectors.items()
                if sector_id != "SEC:ALP:S04_H01"
            }
        }
    )
    with pytest.raises(RouteError, match="gap"):
        expand_route("X", "SEC:ALP:S03_S04:EB", "SEC:ALP:H01_H02:EB", gapped)
