"""Condition API router.

ERD requirements: DET-01, DET-02.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.enums import EvidenceType
from app.domain.models import ConditionEvent
from app.domain.schemas import ConditionEventRead
from app.modules.condition import service

router = APIRouter(prefix="/api/v1", tags=["condition"])


class EvidenceRead(BaseModel):
    """Evidence row attached to a condition event."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    condition_event_id: uuid.UUID | None = None
    assessment_id: uuid.UUID | None = None
    type: EvidenceType
    content: dict
    created_at: datetime


@router.post(
    "/conditions/detect/{component_id}",
    response_model=ConditionEventRead,
    status_code=status.HTTP_201_CREATED,
)
def detect_condition(component_id: uuid.UUID, db: Session = Depends(get_db)) -> ConditionEvent:
    """Run detection for a component using current inputs only."""
    try:
        return service.detect_condition(db, component_id)
    except service.ComponentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="component not found"
        ) from None
    except service.InputNotCurrentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"input not current: {exc.state.value}",
        ) from None


@router.get("/conditions", response_model=list[ConditionEventRead])
def list_conditions(
    component_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> list[ConditionEvent]:
    """List detected condition events."""
    return service.list_conditions(db, component_id)


@router.get("/conditions/{condition_id}", response_model=ConditionEventRead)
def read_condition(condition_id: uuid.UUID, db: Session = Depends(get_db)) -> ConditionEvent:
    """Return one condition event."""
    event = service.get_condition(db, condition_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="condition not found"
        )
    return event


@router.get("/conditions/{condition_id}/evidence", response_model=list[EvidenceRead])
def read_condition_evidence(
    condition_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[EvidenceRead]:
    """List evidence rows for a condition event."""
    event = service.get_condition(db, condition_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="condition not found"
        )
    return service.list_evidence(db, condition_id)
