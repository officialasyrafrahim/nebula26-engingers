"""Read-only LTA DataMall advisory context endpoints.

Everything here is advisory. The endpoints never mutate solver state, never
write to a run and never gate export. They are safe to be unavailable: an
unconfigured key or a DataMall outage returns a labelled unavailable payload,
not an error that could break another endpoint. The development
``X-User-Id``/``X-User-Role`` stub is preserved through ``get_current_user``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import CurrentUser, get_current_user
from app.modules.datamall import mapping
from app.modules.datamall.schemas import (
    CrowdDensityResponse,
    DatamallMappingResponse,
    DatamallStatusResponse,
    NetworkContextResponse,
    OdVolumeResponse,
    PassengerVolumeResponse,
    TrainAlertsResponse,
)
from app.modules.datamall.service import DatamallService, get_datamall_service

router = APIRouter(prefix="/api/v1/context/datamall", tags=["datamall"])


@router.get("/status", response_model=DatamallStatusResponse)
def get_status(
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> DatamallStatusResponse:
    """Report whether DataMall is configured and the freshness per dataset."""

    return service.status()


@router.get("/mapping", response_model=DatamallMappingResponse)
def get_mapping(
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> DatamallMappingResponse:
    """Return the source-cited solver-to-LTA mapping table."""

    return service.mapping()


@router.get("/passenger-volume", response_model=PassengerVolumeResponse)
def get_passenger_volume(
    date: str | None = Query(default=None, pattern=r"^\d{6}$"),
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> PassengerVolumeResponse:
    """Passenger tap-in/tap-out volume per mapped station (PV/Train)."""

    return service.passenger_volume(date)


@router.get("/od-volume", response_model=OdVolumeResponse)
def get_od_volume(
    date: str | None = Query(default=None, pattern=r"^\d{6}$"),
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> OdVolumeResponse:
    """Top mapped origin-destination train trips (PV/ODTrain)."""

    return service.od_volume(date)


def _validated_line(line: str) -> str:
    normalised = line.strip().upper()
    if normalised not in mapping.ALLOWED_LINES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported train line {line!r}. Allowed: {sorted(mapping.ALLOWED_LINES)}",
        )
    return normalised


@router.get("/crowd-density", response_model=CrowdDensityResponse)
def get_crowd_density(
    line: str = Query(...),
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> CrowdDensityResponse:
    """Real-time station crowd density for a mapped train line (PCDRealTime)."""

    return service.crowd_density(_validated_line(line))


@router.get("/crowd-forecast", response_model=CrowdDensityResponse)
def get_crowd_forecast(
    line: str = Query(...),
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> CrowdDensityResponse:
    """Forecast station crowd density for a mapped train line (PCDForecast)."""

    return service.crowd_forecast(_validated_line(line))


@router.get("/alerts", response_model=TrainAlertsResponse)
def get_alerts(
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> TrainAlertsResponse:
    """Train service alerts filtered to the mapped lines (TrainServiceAlerts)."""

    return service.train_service_alerts()


@router.get("/context", response_model=NetworkContextResponse)
def get_context(
    network: str = Query(...),
    service: DatamallService = Depends(get_datamall_service),
    user: CurrentUser = Depends(get_current_user),
) -> NetworkContextResponse:
    """Aggregate advisory context for one mapped demo network."""

    return service.network_context(network)


__all__ = ["router"]
