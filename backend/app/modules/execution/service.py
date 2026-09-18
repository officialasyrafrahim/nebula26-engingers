"""Execution service.

ERD requirements: EXE-01, FBK-01.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import WorkPackageState
from app.domain.models import Assessment, MaintenanceOutcome, WorkPackage, utcnow
from app.domain.schemas import OutcomeCreate


def _parse_uuid(value: object) -> uuid.UUID | None:
    """Parse a UUID-like value, returning None when invalid."""
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _load_work_package(db: Session, work_package_id: uuid.UUID) -> WorkPackage:
    """Fetch a work package or raise 404."""
    work_package = db.get(WorkPackage, work_package_id)
    if work_package is None:
        raise HTTPException(status_code=404, detail="work package not found")
    return work_package


def assign_work_package(
    db: Session,
    work_package_id: uuid.UUID,
    technician_id: uuid.UUID | None = None,
    crew_id: uuid.UUID | None = None,
    depot_id: uuid.UUID | None = None,
) -> WorkPackage:
    """Assign a planned work package to a technician or crew."""
    work_package = _load_work_package(db, work_package_id)
    allowed = (
        WorkPackageState.CREATED,
        WorkPackageState.PLANNED,
        WorkPackageState.APPROVED,
    )
    if work_package.state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"cannot assign work package in state {work_package.state.value}",
        )
    work_package.state = WorkPackageState.ASSIGNED
    work_package.assigned_technician_id = technician_id
    work_package.assigned_crew_id = crew_id
    db.commit()
    db.refresh(work_package)
    return work_package


def start_work_package(db: Session, work_package_id: uuid.UUID) -> WorkPackage:
    """Mark a work package as in progress."""
    work_package = _load_work_package(db, work_package_id)
    work_package.state = WorkPackageState.IN_PROGRESS
    db.commit()
    db.refresh(work_package)
    return work_package


def complete_work_package(db: Session, work_package_id: uuid.UUID) -> WorkPackage:
    """Mark a work package as completed."""
    work_package = _load_work_package(db, work_package_id)
    work_package.state = WorkPackageState.COMPLETED
    db.commit()
    db.refresh(work_package)
    return work_package


def record_outcome(
    db: Session, data: OutcomeCreate, technician_id: object | None = None
) -> MaintenanceOutcome:
    """Record the actual finding, linked to the originating prediction."""
    work_package = _load_work_package(db, data.work_package_id)
    condition_event_id = data.condition_event_id
    if condition_event_id is None:
        assessment = db.get(Assessment, work_package.assessment_id)
        if assessment is not None:
            condition_event_id = assessment.condition_event_id

    outcome = MaintenanceOutcome(
        work_package_id=work_package.id,
        condition_event_id=condition_event_id,
        technician_id=_parse_uuid(technician_id),
        finding_type=data.finding_type,
        actual_finding=data.actual_finding,
        actual_duration_min=data.actual_duration_min,
        parts_used=data.parts_used,
        recorded_at=utcnow(),
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome


def list_outcomes(db: Session) -> list[MaintenanceOutcome]:
    """List recorded maintenance outcomes."""
    return list(
        db.scalars(
            select(MaintenanceOutcome).order_by(MaintenanceOutcome.recorded_at.desc())
        ).all()
    )


def get_outcome(db: Session, outcome_id: uuid.UUID) -> MaintenanceOutcome | None:
    """Fetch a maintenance outcome by identifier."""
    return db.get(MaintenanceOutcome, outcome_id)
