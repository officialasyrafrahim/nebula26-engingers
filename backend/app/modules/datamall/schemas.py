"""Response contracts for the optional LTA DataMall advisory context.

Every payload carries the advisory label, the provisional disclaimer and the
source freshness so the UI can never present the data as a solver input. The
DataMall account key is never part of any schema here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DatamallState = Literal["ok", "empty", "unconfigured", "error"]

ADVISORY_LABEL = "Advisory context, not used in scoring"
ADVISORY_DISCLAIMER = (
    "LTA DataMall supplies passenger tap volumes and a coarse low/moderate/high "
    "station crowding band only. It is not train capacity or onboard occupancy. "
    "It is never used for PS1 supply, validation, scoring, feasibility or the "
    "published CSVs."
)
MEASUREMENT_NOTE = (
    "Passenger volume is a monthly tap-in/tap-out aggregate. Station crowd "
    "density is the LTA low/moderate/high band for a time interval. Neither is "
    "a measurement of train capacity or onboard load."
)
UNAVAILABLE_NETWORK_REASON = "DataMall context unavailable for this network"
UNCONFIGURED_REASON = (
    "LTA DataMall is off. Set LTA_DATAMALL_ACCOUNT_KEY to enable advisory context."
)


class DatamallAdvisory(BaseModel):
    """The advisory banner attached to every DataMall payload."""

    advisory: bool = True
    label: str = ADVISORY_LABEL
    disclaimer: str = ADVISORY_DISCLAIMER
    measurement_note: str = MEASUREMENT_NOTE


class DatamallSource(BaseModel):
    """Retrieval time and source status for one LTA dataset call."""

    dataset: str
    source: str
    source_url: str
    interval: str
    state: DatamallState
    available: bool
    configured: bool
    retrieved_at: datetime | None = None
    cached: bool = False
    http_status: int | None = None
    reason: str | None = None


class PassengerVolumeRecord(BaseModel):
    station_code: str
    station_name: str | None = None
    solver_line: str | None = None
    solver_station: str | None = None
    datamall_line: str | None = None
    tap_in_weekday: int | None = None
    tap_out_weekday: int | None = None
    tap_in_weekend: int | None = None
    tap_out_weekend: int | None = None
    total_weekday: int | None = None
    total_weekend: int | None = None


class OdVolumeRecord(BaseModel):
    origin_code: str
    origin_name: str | None = None
    destination_code: str
    destination_name: str | None = None
    weekday_trips: int = 0
    weekend_trips: int = 0


class CrowdDensityRecord(BaseModel):
    station_code: str
    station_name: str | None = None
    solver_line: str | None = None
    solver_station: str | None = None
    datamall_line: str | None = None
    crowd_level: str
    interval_start: str | None = None
    interval_end: str | None = None


class TrainAlertRecord(BaseModel):
    line: str | None = None
    direction: str | None = None
    stations: list[str] = Field(default_factory=list)
    free_public_bus: list[str] = Field(default_factory=list)
    free_mrt_shuttle: list[str] = Field(default_factory=list)
    message: str | None = None
    created_at: str | None = None


class PassengerVolumeResponse(BaseModel):
    source: DatamallSource
    advisory: DatamallAdvisory = Field(default_factory=DatamallAdvisory)
    period: str | None = None
    records: list[PassengerVolumeRecord] = Field(default_factory=list)


class OdVolumeResponse(BaseModel):
    source: DatamallSource
    advisory: DatamallAdvisory = Field(default_factory=DatamallAdvisory)
    period: str | None = None
    records: list[OdVolumeRecord] = Field(default_factory=list)


class CrowdDensityResponse(BaseModel):
    source: DatamallSource
    advisory: DatamallAdvisory = Field(default_factory=DatamallAdvisory)
    line: str | None = None
    records: list[CrowdDensityRecord] = Field(default_factory=list)


class TrainAlertsResponse(BaseModel):
    source: DatamallSource
    advisory: DatamallAdvisory = Field(default_factory=DatamallAdvisory)
    # 1 is normal service or minor delays, 2 is a disruption.
    status: int | None = None
    records: list[TrainAlertRecord] = Field(default_factory=list)


class DatamallStatusResponse(BaseModel):
    configured: bool
    enabled: bool
    state: DatamallState
    reason: str | None = None
    datasets: list[DatamallSource] = Field(default_factory=list)


class MappingStationRead(BaseModel):
    solver_line: str
    solver_station: str
    name: str
    code: str
    datamall_line: str


class MappingNetworkRead(BaseModel):
    key: str
    label: str
    solver_lines: list[str]
    crowd_lines: list[str]
    alert_lines: list[str]
    stations: list[MappingStationRead]


class DatamallMappingResponse(BaseModel):
    source: str
    source_url: str
    caveat: str
    networks: list[MappingNetworkRead]


class NetworkContextResponse(BaseModel):
    network: str
    supported: bool
    advisory: DatamallAdvisory = Field(default_factory=DatamallAdvisory)
    generated_at: datetime
    mapping: MappingNetworkRead | None = None
    reason: str | None = None
    sources: list[DatamallSource] = Field(default_factory=list)
    passenger_volume: list[PassengerVolumeRecord] = Field(default_factory=list)
    od_volume: list[OdVolumeRecord] = Field(default_factory=list)
    crowd_density: list[CrowdDensityRecord] = Field(default_factory=list)
    crowd_forecast: list[CrowdDensityRecord] = Field(default_factory=list)
    alerts: list[TrainAlertRecord] = Field(default_factory=list)
    alerts_status: int | None = None


__all__ = [
    "ADVISORY_DISCLAIMER",
    "ADVISORY_LABEL",
    "MEASUREMENT_NOTE",
    "UNAVAILABLE_NETWORK_REASON",
    "UNCONFIGURED_REASON",
    "CrowdDensityRecord",
    "CrowdDensityResponse",
    "DatamallAdvisory",
    "DatamallMappingResponse",
    "DatamallSource",
    "DatamallState",
    "DatamallStatusResponse",
    "MappingNetworkRead",
    "MappingStationRead",
    "NetworkContextResponse",
    "OdVolumeRecord",
    "OdVolumeResponse",
    "PassengerVolumeRecord",
    "PassengerVolumeResponse",
    "TrainAlertRecord",
    "TrainAlertsResponse",
]
