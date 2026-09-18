"""Assessment API router.

ERD requirements: ASM-01, ASM-02, ASM-03, WPK-01.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.enums import EvidenceType
from app.domain.models import Assessment, Evidence, WorkPackage
from app.domain.schemas import AssessmentRead, WorkPackageRead
from app.modules.assessment import service

router = APIRouter(prefix="/api/v1", tags=["assessment"])


class AssessmentRequest(BaseModel):
    """Request to assess an existing condition event."""

    condition_event_id: uuid.UUID


class WorkPackageRequest(BaseModel):
    """Request to package an assessment into actionable work."""

    assessment_id: uuid.UUID
    title: str | None = None
    recommended_action: str | None = None


class EvidenceRead(BaseModel):
    """Evidence row attached to an assessment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    condition_event_id: uuid.UUID | None = None
    assessment_id: uuid.UUID | None = None
    type: EvidenceType
    content: dict
    created_at: datetime


@router.post(
    "/assessments", response_model=AssessmentRead, status_code=status.HTTP_201_CREATED
)
def create_assessment(
    data: AssessmentRequest, db: Session = Depends(get_db)
) -> Assessment:
    """Assess a condition event with deterministic rules."""
    try:
        return service.assess_condition(db, data.condition_event_id)
    except service.ConditionEventNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="condition event not found"
        ) from None


@router.get("/assessments", response_model=list[AssessmentRead])
def list_assessments(db: Session = Depends(get_db)) -> list[Assessment]:
    """List assessments."""
    return service.list_assessments(db)


@router.get("/assessments/{assessment_id}", response_model=AssessmentRead)
def read_assessment(assessment_id: uuid.UUID, db: Session = Depends(get_db)) -> Assessment:
    """Return one assessment."""
    assessment = service.get_assessment(db, assessment_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="assessment not found"
        )
    return assessment


@router.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceRead])
def read_assessment_evidence(
    assessment_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[Evidence]:
    """List evidence rows for an assessment."""
    assessment = service.get_assessment(db, assessment_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="assessment not found"
        )
    return service.list_evidence(db, assessment_id)


@router.post(
    "/work-packages", response_model=WorkPackageRead, status_code=status.HTTP_201_CREATED
)
def create_work_package(
    data: WorkPackageRequest, db: Session = Depends(get_db)
) -> WorkPackage:
    """Create a work package from an actionable assessment."""
    try:
        return service.create_work_package(
            db, data.assessment_id, data.title, data.recommended_action
        )
    except service.AssessmentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="assessment not found"
        ) from None


@router.get("/work-packages", response_model=list[WorkPackageRead])
def list_work_packages(db: Session = Depends(get_db)) -> list[WorkPackage]:
    """List work packages."""
    return service.list_work_packages(db)


@router.get("/work-packages/{work_package_id}", response_model=WorkPackageRead)
def read_work_package(
    work_package_id: uuid.UUID, db: Session = Depends(get_db)
) -> WorkPackage:
    """Return one work package."""
    work_package = service.get_work_package(db, work_package_id)
    if work_package is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="work package not found"
        )
    return work_package
