"""Execution API router.

ERD requirements: EXE-01, FBK-01.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.domain.schemas import MaintenanceOutcomeRead, OutcomeCreate, WorkPackageRead
from app.modules.execution import service

router = APIRouter(prefix="/api/v1", tags=["execution"])


class AssignmentRequest(BaseModel):
    """Request body for assigning a work package."""

    technician_id: uuid.UUID | None = None
    crew_id: uuid.UUID | None = None


@router.post("/work-packages/{work_package_id}/assign", response_model=WorkPackageRead)
def assign_work_package(
    work_package_id: uuid.UUID,
    body: AssignmentRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> WorkPackageRead:
    """Assign a planned work package."""
    return service.assign_work_package(db, work_package_id, body.technician_id, body.crew_id)


@router.post("/work-packages/{work_package_id}/start", response_model=WorkPackageRead)
def start_work_package(
    work_package_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.TECHNICIAN, UserRole.ADMIN)),
) -> WorkPackageRead:
    """Start work on a work package."""
    return service.start_work_package(db, work_package_id)


@router.post("/work-packages/{work_package_id}/complete", response_model=WorkPackageRead)
def complete_work_package(
    work_package_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.TECHNICIAN, UserRole.ADMIN)),
) -> WorkPackageRead:
    """Complete a work package."""
    return service.complete_work_package(db, work_package_id)


@router.post(
    "/outcomes",
    response_model=MaintenanceOutcomeRead,
    status_code=status.HTTP_201_CREATED,
)
def record_outcome(
    data: OutcomeCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.TECHNICIAN, UserRole.ADMIN)),
) -> MaintenanceOutcomeRead:
    """Record a maintenance outcome."""
    return service.record_outcome(db, data, user.id)


@router.get("/outcomes", response_model=list[MaintenanceOutcomeRead])
def list_outcomes(db: Session = Depends(get_db)) -> list[MaintenanceOutcomeRead]:
    """List recorded outcomes."""
    return service.list_outcomes(db)


@router.get("/outcomes/{outcome_id}", response_model=MaintenanceOutcomeRead)
def get_outcome(outcome_id: uuid.UUID, db: Session = Depends(get_db)) -> MaintenanceOutcomeRead:
    """Fetch a recorded outcome."""
    outcome = service.get_outcome(db, outcome_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="outcome not found")
    return outcome
