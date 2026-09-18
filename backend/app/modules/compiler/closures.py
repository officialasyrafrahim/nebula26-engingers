"""Buffer closure, opposite-bound mirroring and H01-H02 interchange effects.

All effects are derived from ``05_BUFFER_LOCATION.csv`` and the network tables,
never hard-coded per activity (INP-04 / SCH-04 / SCH-05).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.rail.instance_model import PlanningInstance
from app.domain.rail.keys import (
    flip_bound,
    format_location_id,
    format_sector_id,
    parse_location_id,
    replace_location_bound,
)
from app.domain.rail.routes import Route

LIVE_NATURE = "Live"
INTERCHANGE_FROM = "H01"
INTERCHANGE_TO = "H02"


class ClosureError(ValueError):
    """Raised when a closure cannot be derived from the network."""


class ClosureResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector_ids: tuple[str, ...]
    location_ids: tuple[str, ...]


def buffered_closure(
    instance: PlanningInstance,
    route: Route,
    buffer_sectors: int,
) -> ClosureResult:
    """Extend the occupied sector span by ``buffer_sectors`` on both ends."""

    line_code = route.line_code
    bound = route.bound
    line_sectors = instance.sectors_on_line(line_code)
    if not line_sectors:
        raise ClosureError(f"no tunnel sectors published for line {line_code!r}")

    by_id = {sector.sector_id: sector for sector in line_sectors}
    try:
        route_sequences = [by_id[sector_id].seq for sector_id in route.sector_ids]
    except KeyError as exc:  # pragma: no cover - routes are pre-validated
        raise ClosureError(f"route {route.activity_id!r} references unknown sector {exc}") from exc

    low = max(min(route_sequences) - buffer_sectors, line_sectors[0].seq)
    high = min(max(route_sequences) + buffer_sectors, line_sectors[-1].seq)
    span = [sector for sector in line_sectors if low <= sector.seq <= high]

    station_sequences: list[int] = []
    for sector in span:
        for station_id in (sector.from_station_id, sector.to_station_id):
            station = instance.stations.get((line_code, station_id))
            if station is None:  # pragma: no cover - network is pre-validated
                raise ClosureError(
                    f"sector {sector.sector_id!r} references unknown station {station_id!r}"
                )
            station_sequences.append(station.seq)

    station_low, station_high = min(station_sequences), max(station_sequences)
    span_stations = [
        station
        for station in instance.stations_on_line(line_code)
        if station_low <= station.seq <= station_high
    ]

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
        for sector in span
    )
    return ClosureResult(
        sector_ids=tuple(sector.sector_id for sector in span),
        location_ids=platforms + tunnels,
    )


def mirrored_locations(location_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Mirror a set of locations onto the opposite bound of the same line."""

    mirrored: list[str] = []
    for location_id in location_ids:
        key = parse_location_id(location_id)
        mirrored.append(replace_location_bound(location_id, flip_bound(key.bound)))
    return tuple(dict.fromkeys(mirrored))


def interchange_triggered(
    route: Route,
    closure: ClosureResult,
) -> bool:
    """Whether a Live closure span reaches the line's H01-H02 tunnel sector."""

    interchange_sector = format_location_id(
        kind="SEC",
        line_code=route.line_code,
        bound=route.bound,
        sector_id=format_sector_id(
            route.line_code, INTERCHANGE_FROM, INTERCHANGE_TO
        ),
    )
    return interchange_sector in closure.location_ids


def interchange_locations(
    instance: PlanningInstance,
    own_line: str,
) -> tuple[str, ...]:
    """Add the other line's H01/H02 sector and platforms, both bounds (A-4)."""

    others = sorted(line for line in instance.lines if line != own_line)
    if len(others) != 1:
        return ()
    other_line = others[0]

    locations: list[str] = []
    for other_bound in ("EB", "WB"):
        locations.append(
            format_location_id(
                kind="SEC",
                line_code=other_line,
                bound=other_bound,
                sector_id=format_sector_id(other_line, INTERCHANGE_FROM, INTERCHANGE_TO),
            )
        )
        for station_id in (INTERCHANGE_FROM, INTERCHANGE_TO):
            locations.append(
                format_location_id(
                    kind="PLAT",
                    line_code=other_line,
                    bound=other_bound,
                    station_id=station_id,
                )
            )
    return tuple(location for location in locations if location in instance.locations)
