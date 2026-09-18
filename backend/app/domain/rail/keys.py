"""Natural-key parsing and formatting for the rail network.

The published CSVs identify everything with human-readable strings. The
canonical model keeps those natural keys and never introduces surrogate ids.
Only two shapes need parsing:

* tunnel sector id:  ``SEC:<line_code>:<from_station>_<to_station>``
* location id:       ``SEC:<line_code>:<from>_<to>:<bound>``
  or                 ``PLAT:<line_code>:<station>:<bound>``
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

LocationKind = Literal["SEC", "PLAT"]
Bound = Literal["EB", "WB"]

BOUNDS: tuple[Bound, ...] = ("EB", "WB")


class NaturalKeyError(ValueError):
    """Raised when a natural key does not match its published form."""


class SectorKey(BaseModel):
    """The three components that make up a tunnel sector id."""

    model_config = ConfigDict(frozen=True)

    line_code: str
    from_station_id: str
    to_station_id: str

    @property
    def sector_id(self) -> str:
        return format_sector_id(self.line_code, self.from_station_id, self.to_station_id)


class LocationKey(BaseModel):
    """The parsed form of a tunnel or platform location id."""

    model_config = ConfigDict(frozen=True)

    kind: LocationKind
    line_code: str
    bound: Bound
    station_id: str | None = None
    sector_id: str | None = None

    @property
    def is_tunnel(self) -> bool:
        return self.kind == "SEC"

    @property
    def is_platform(self) -> bool:
        return self.kind == "PLAT"


def _require(value: str, label: str) -> str:
    if not value:
        raise NaturalKeyError(f"{label} must not be empty")
    return value


def parse_sector_id(sector_id: str) -> SectorKey:
    """Parse ``SEC:<line>:<from>_<to>`` into a :class:`SectorKey`."""

    parts = sector_id.split(":")
    if len(parts) != 3 or parts[0] != "SEC":
        raise NaturalKeyError(f"malformed tunnel sector id: {sector_id!r}")
    line_code = _require(parts[1], "line_code")
    span = parts[2]
    if "_" not in span:
        raise NaturalKeyError(f"malformed tunnel sector span: {sector_id!r}")
    from_station_id, _, to_station_id = span.partition("_")
    return SectorKey(
        line_code=line_code,
        from_station_id=_require(from_station_id, "from_station_id"),
        to_station_id=_require(to_station_id, "to_station_id"),
    )


def format_sector_id(line_code: str, from_station_id: str, to_station_id: str) -> str:
    return f"SEC:{line_code}:{from_station_id}_{to_station_id}"


def parse_location_id(location_id: str) -> LocationKey:
    """Parse a tunnel-sector or platform-sector location id."""

    parts = location_id.split(":")
    if len(parts) != 4:
        raise NaturalKeyError(f"malformed location id: {location_id!r}")
    kind, line_code, middle, bound = parts
    if bound not in BOUNDS:
        raise NaturalKeyError(f"unknown bound {bound!r} in location id {location_id!r}")
    if kind == "SEC":
        if "_" not in middle:
            raise NaturalKeyError(f"malformed tunnel location id: {location_id!r}")
        from_station_id, _, to_station_id = middle.partition("_")
        return LocationKey(
            kind="SEC",
            line_code=_require(line_code, "line_code"),
            bound=bound,
            sector_id=format_sector_id(line_code, from_station_id, to_station_id),
        )
    if kind == "PLAT":
        return LocationKey(
            kind="PLAT",
            line_code=_require(line_code, "line_code"),
            bound=bound,
            station_id=_require(middle, "station_id"),
        )
    raise NaturalKeyError(f"unknown location kind {kind!r} in {location_id!r}")


def format_location_id(
    *,
    kind: LocationKind,
    line_code: str,
    bound: Bound,
    station_id: str | None = None,
    sector_id: str | None = None,
) -> str:
    """Build a canonical location id from its components."""

    if kind == "PLAT":
        if not station_id:
            raise NaturalKeyError("platform location requires station_id")
        return f"PLAT:{line_code}:{station_id}:{bound}"
    if kind == "SEC":
        if not sector_id:
            raise NaturalKeyError("tunnel location requires sector_id")
        key = parse_sector_id(sector_id)
        return f"SEC:{key.line_code}:{key.from_station_id}_{key.to_station_id}:{bound}"
    raise NaturalKeyError(f"unknown location kind: {kind!r}")


def flip_bound(bound: Bound) -> Bound:
    """Return the opposite running line bound."""

    return "WB" if bound == "EB" else "EB"


def replace_location_bound(location_id: str, bound: Bound) -> str:
    """Return ``location_id`` with its bound replaced by ``bound``."""

    key = parse_location_id(location_id)
    return format_location_id(
        kind=key.kind,
        line_code=key.line_code,
        bound=bound,
        station_id=key.station_id,
        sector_id=key.sector_id,
    )
