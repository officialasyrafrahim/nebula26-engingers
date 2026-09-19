"""Canonical network records keyed by the published natural identifiers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.rail.strict_types import StrictBool, StrictInt

LocationKindLabel = Literal["tunnel sector", "platform sector"]


class _FrozenRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Line(_FrozenRecord):
    line_code: str
    line_name: str


class Station(_FrozenRecord):
    station_id: str
    line_code: str
    seq: StrictInt = Field(ge=1)
    is_interchange: StrictBool = False


class Sector(_FrozenRecord):
    sector_id: str
    line_code: str
    from_station_id: str
    to_station_id: str
    seq: StrictInt = Field(ge=1)
    is_shared: StrictBool = False


class LocationSupply(_FrozenRecord):
    location_id: str
    location_kind: LocationKindLabel
    line_code: str
    bound: str
    supply_capacity: StrictInt = Field(ge=1)


class BufferRule(_FrozenRecord):
    nature_of_works: str
    up_to_buffer_sectors: StrictInt = Field(ge=0)
    opposite_bound_required: StrictBool = False


StationKey = tuple[str, str]
