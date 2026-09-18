"""Ingestion API router.

ERD requirements: DAT-01, DAT-02, PERF-01.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.enums import DataQualityState
from app.domain.schemas import DataSourceStateRead
from app.modules.ingestion import service

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


class RejectedRowRead(BaseModel):
    """Rejected batch row with index and reason."""

    index: int
    reason: str


class IngestResultRead(BaseModel):
    """Per-batch ingestion report."""

    accepted: int
    rejected: list[RejectedRowRead]


class SourceSummaryRead(BaseModel):
    """Registered source with its current quality state."""

    id: uuid.UUID
    key: str
    description: str | None = None
    state: DataQualityState | None = None
    last_valid_ts: datetime | None = None
    updated_at: datetime | None = None


@router.post("/ingest/telemetry", response_model=IngestResultRead)
def ingest_telemetry(
    readings: list[Any], db: Session = Depends(get_db)
) -> IngestResultRead:
    """Validate and persist a telemetry batch, reporting rejects per row."""
    result = service.ingest_telemetry_batch(db, readings)
    return IngestResultRead(
        accepted=result.accepted,
        rejected=[RejectedRowRead(index=row.index, reason=row.reason) for row in result.rejected],
    )


@router.get("/ingest/sources", response_model=list[SourceSummaryRead])
def list_sources(db: Session = Depends(get_db)) -> list[SourceSummaryRead]:
    """List registered sources and their current quality states."""
    return [
        SourceSummaryRead(
            id=source.id,
            key=source.key,
            description=source.description,
            state=state.state if state is not None else None,
            last_valid_ts=state.last_valid_ts if state is not None else None,
            updated_at=state.updated_at if state is not None else None,
        )
        for source, state in service.list_source_states(db)
    ]


@router.get("/ingest/sources/{source_id}/state", response_model=DataSourceStateRead)
def read_source_state(source_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return the current quality state for a source."""
    state = service.get_source_state(db, source_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source not found")
    return state
