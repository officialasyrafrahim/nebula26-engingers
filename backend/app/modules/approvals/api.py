"""Approvals API router.

ERD requirements: HUM-01, HUM-02, AUD-02.
"""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.domain.schemas import (
    ApprovalCreate,
    ApprovalRead,
    PublishedScheduleRead,
)
from app.modules.approvals import service

router = APIRouter(prefix="/api/v1", tags=["approvals"])


class PublishRequest(BaseModel):
    """Request body for publishing an approved schedule."""

    proposal_id: uuid.UUID


@router.post("/approvals", response_model=ApprovalRead, status_code=status.HTTP_201_CREATED)
def decide_approval(
    data: ApprovalCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> ApprovalRead:
    """Record a human approval decision."""
    return service.decide_approval(db, data, user)


@router.get("/approvals", response_model=list[ApprovalRead])
def list_approvals(
    work_package_id: uuid.UUID | None = None,
    proposal_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[ApprovalRead]:
    """List approvals, optionally filtered."""
    return service.list_approvals(db, work_package_id, proposal_id)


@router.post(
    "/schedules/publish",
    response_model=PublishedScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def publish_schedule(
    body: PublishRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> PublishedScheduleRead:
    """Publish an approved schedule."""
    return service.publish_schedule(db, body.proposal_id, published_by=user.id)


@router.get("/schedules/published", response_model=list[PublishedScheduleRead])
def list_published_schedules(db: Session = Depends(get_db)) -> list[PublishedScheduleRead]:
    """List published schedules."""
    return service.list_published(db)
