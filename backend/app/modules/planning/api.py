"""Planning API router.

ERD requirements: PLN-01, PLN-02, PLN-03, PLN-04, RPL-01.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import ProposalState, UserRole
from app.domain.schemas import (
    PlanJobRead,
    PlanJobSubmit,
    ScheduleAssignmentRead,
    ScheduleProposalRead,
)
from app.modules.planning import service

router = APIRouter(prefix="/api/v1", tags=["planning"])


class PlanInvalidationRequest(BaseModel):
    """Request body for invalidating a proposal."""

    trigger: str
    reason: str | None = None


class PlanInvalidationResponse(BaseModel):
    """Result of invalidating a proposal and enqueueing a replan."""

    invalidation_id: uuid.UUID
    proposal_state: ProposalState
    replan_job_id: uuid.UUID


@router.post("/planning/jobs", response_model=PlanJobRead, status_code=status.HTTP_202_ACCEPTED)
def submit_plan_job(
    data: PlanJobSubmit,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> PlanJobRead:
    """Queue a planning job and return immediately."""
    return service.submit_plan_job(db, data, user.id)


@router.get("/planning/jobs", response_model=list[PlanJobRead])
def list_plan_jobs(db: Session = Depends(get_db)) -> list[PlanJobRead]:
    """List planning jobs."""
    return service.list_jobs(db)


@router.get("/planning/jobs/{job_id}", response_model=PlanJobRead)
def get_plan_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> PlanJobRead:
    """Fetch a planning job."""
    job = service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="plan job not found")
    return job


@router.get(
    "/planning/jobs/{job_id}/proposals",
    response_model=list[ScheduleProposalRead],
)
def list_job_proposals(
    job_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[ScheduleProposalRead]:
    """List materially different alternatives produced for a job."""
    if service.get_job(db, job_id) is None:
        raise HTTPException(status_code=404, detail="plan job not found")
    return service.list_proposals(db, job_id)


@router.post("/planning/jobs/{job_id}/cancel", response_model=PlanJobRead)
def cancel_plan_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> PlanJobRead:
    """Cancel a queued or running planning job."""
    return service.cancel_job(db, job_id)


@router.get("/planning/proposals/{proposal_id}", response_model=ScheduleProposalRead)
def get_schedule_proposal(
    proposal_id: uuid.UUID, db: Session = Depends(get_db)
) -> ScheduleProposalRead:
    """Fetch a schedule proposal."""
    proposal = service.get_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return proposal


@router.get(
    "/planning/proposals/{proposal_id}/assignments",
    response_model=list[ScheduleAssignmentRead],
)
def list_schedule_assignments(
    proposal_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[ScheduleAssignmentRead]:
    """List assignments for a proposal."""
    proposal = service.get_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return service.list_assignments(db, proposal_id)


@router.post(
    "/planning/proposals/{proposal_id}/invalidate",
    response_model=PlanInvalidationResponse,
    status_code=status.HTTP_201_CREATED,
)
def invalidate_schedule_proposal(
    proposal_id: uuid.UUID,
    body: PlanInvalidationRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> PlanInvalidationResponse:
    """Invalidate a proposal and enqueue a replan for remaining work."""
    invalidation = service.invalidate_proposal(db, proposal_id, body.trigger, body.reason)
    return PlanInvalidationResponse(
        invalidation_id=invalidation.id,
        proposal_state=ProposalState.INVALIDATED,
        replan_job_id=invalidation.replan_job_id,
    )
