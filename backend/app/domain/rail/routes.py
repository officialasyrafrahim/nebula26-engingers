"""Route expansion from book-in to book-out.

An activity names a start and end tunnel sector on one line and one bound.
Expansion is a pure function of the network tables: every tunnel sector and
platform location between the two endpoints (inclusive) is occupied. Direction
does not change the occupied set; a route is an unordered span.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.domain.rail.keys import (
    LocationKey,
    format_location_id,
    parse_location_id,
    parse_sector_id,
)
from app.domain.rail.network import LocationSupply, Sector, Station, StationKey


class RouteError(ValueError):
    """Raised when start and end locations do not form a traversable route."""


class RouteNetwork(BaseModel):
    """The slices of the network needed to expand a route."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    stations: Mapping[StationKey, Station]
    sectors: Mapping[str, Sector]
    locations: Mapping[str, LocationSupply]


class Route(BaseModel):
    """The ordered, inclusive occupancy of one activity."""

    model_config = ConfigDict(frozen=True)

    activity_id: str
    line_code: str
    bound: str
    start_station_id: str
    end_station_id: str
    station_ids: tuple[str, ...]
    sector_ids: tuple[str, ...]
    location_ids: tuple[str, ...]

    @property
    def occupied_location_ids(self) -> frozenset[str]:
        return frozenset(self.location_ids)


def _endpoint_location(location_id: str, label: str) -> LocationKey:
    try:
        key = parse_location_id(location_id)
    except ValueError as exc:
        raise RouteError(f"{label} is not a valid location id: {location_id!r}") from exc
    if not key.is_tunnel:
        raise RouteError(f"{label} must be a tunnel sector location: {location_id!r}")
    return key


def _sector(sector_id: str, network: RouteNetwork, label: str) -> Sector:
    sector = network.sectors.get(sector_id)
    if sector is None:
        raise RouteError(f"{label} references unknown tunnel sector: {sector_id!r}")
    parsed = parse_sector_id(sector.sector_id)
    if (
        parsed.line_code != sector.line_code
        or parsed.from_station_id != sector.from_station_id
        or parsed.to_station_id != sector.to_station_id
    ):
        raise RouteError(
            f"tunnel sector id {sector_id!r} disagrees with its from/to stations "
            f"({sector.from_station_id!r} -> {sector.to_station_id!r})"
        )
    return sector


def expand_route(
    activity_id: str,
    start_location_id: str,
    end_location_id: str,
    network: RouteNetwork,
) -> Route:
    """Expand an activity span into every occupied platform and tunnel location."""

    start = _endpoint_location(start_location_id, "start_location_id")
    end = _endpoint_location(end_location_id, "end_location_id")

    if start.line_code != end.line_code:
        raise RouteError(
            f"route crosses lines: {start_location_id!r} is {start.line_code}, "
            f"{end_location_id!r} is {end.line_code}"
        )
    if start.bound != end.bound:
        raise RouteError(
            f"route crosses bounds: {start_location_id!r} is {start.bound}, "
            f"{end_location_id!r} is {end.bound}"
        )

    line_code = start.line_code
    bound = start.bound
    start_sector = _sector(start.sector_id or "", network, "start_location_id")
    end_sector = _sector(end.sector_id or "", network, "end_location_id")
    for sector in (start_sector, end_sector):
        if sector.line_code != line_code:
            raise RouteError(
                f"tunnel sector {sector.sector_id!r} belongs to {sector.line_code}, "
                f"not {line_code}"
            )

    low, high = sorted((start_sector.seq, end_sector.seq))
    line_sectors = sorted(
        (sector for sector in network.sectors.values() if sector.line_code == line_code),
        key=lambda sector: sector.seq,
    )
    span_sectors = [sector for sector in line_sectors if low <= sector.seq <= high]
    if len(span_sectors) != high - low + 1:
        raise RouteError(
            f"route span {start_location_id!r} -> {end_location_id!r} has a gap in the "
            f"sector sequence [{low}, {high}]"
        )

    station_sequences: list[int] = []
    for sector in span_sectors:
        for station_id in (sector.from_station_id, sector.to_station_id):
            station = network.stations.get((line_code, station_id))
            if station is None:
                raise RouteError(
                    f"tunnel sector {sector.sector_id!r} references unknown station "
                    f"{station_id!r} on {line_code}"
                )
            station_sequences.append(station.seq)

    station_low, station_high = min(station_sequences), max(station_sequences)
    line_stations = sorted(
        (station for (line, _), station in network.stations.items() if line == line_code),
        key=lambda station: station.seq,
    )
    span_stations = [
        station for station in line_stations if station_low <= station.seq <= station_high
    ]
    if len(span_stations) != station_high - station_low + 1:
        raise RouteError(
            f"route span {start_location_id!r} -> {end_location_id!r} has a gap in the "
            f"station sequence [{station_low}, {station_high}]"
        )

    platforms = tuple(
        format_location_id(
            kind="PLAT",
            line_code=line_code,
            bound=bound,
            station_id=station.station_id,
        )
        for station in span_stations
    )
    tunnels = tuple(
        format_location_id(
            kind="SEC",
            line_code=line_code,
            bound=bound,
            sector_id=sector.sector_id,
        )
        for sector in span_sectors
    )
    for location_id in platforms + tunnels:
        if location_id not in network.locations:
            raise RouteError(
                f"route {activity_id!r} needs location {location_id!r} which is absent "
                f"from 04_LOCATION_SUPPLY.csv"
            )

    return Route(
        activity_id=activity_id,
        line_code=line_code,
        bound=bound,
        start_station_id=start_sector.from_station_id,
        end_station_id=end_sector.to_station_id,
        station_ids=tuple(station.station_id for station in span_stations),
        sector_ids=tuple(sector.sector_id for sector in span_sectors),
        location_ids=platforms + tunnels,
    )
