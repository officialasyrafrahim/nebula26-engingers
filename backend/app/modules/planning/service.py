"""Planning service.

ERD requirements: PLN-01, PLN-02, PLN-03, PLN-04, RPL-01.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import JobState, ProposalState, WorkPackageState
from app.domain.models import (
    PlanInvalidation,
    PlanJob,
    ScheduleAssignment,
    ScheduleProposal,
    WorkPackage,
    utcnow,
)
from app.domain.schemas import PlanJobSubmit
from app.modules.planning.queue import get_queue


def _iso(value: datetime | None) -> str | None:
    """Serialize a timestamp for JSON storage."""
    return value.isoformat() if value is not None else None


def submit_plan_job(
    db: Session, data: PlanJobSubmit, requested_by: str | None = None
) -> PlanJob:
    """Validate work packages and create a queued planning job."""
    requested_ids = list(dict.fromkeys(data.work_package_ids))
    existing = set(
        db.scalars(select(WorkPackage.id).where(WorkPackage.id.in_(requested_ids))).all()
    )
    unknown = [
        str(work_package_id)
        for work_package_id in requested_ids
        if work_package_id not in existing
    ]
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_work_package_ids": unknown})

    job = PlanJob(
        state=JobState.QUEUED,
        submitted_at=utcnow(),
        time_limit_seconds=get_settings().solver_time_limit_seconds,
        request={
            "work_package_ids": [str(work_package_id) for work_package_id in requested_ids],
            "horizon_start": _iso(data.horizon_start),
            "horizon_end": _iso(data.horizon_end),
            "notes": data.notes,
            "actor": requested_by,
            "alternatives": data.alternatives,
            "objective_profile": data.objective_profile,
            "constraints": data.constraints.model_dump(mode="json"),
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    # TODO(PLN-04): durable transport; never solve inline on the request path.
    get_queue().enqueue(job.id)
    return job


def get_job(db: Session, job_id: uuid.UUID) -> PlanJob | None:
    """Fetch a planning job by identifier."""
    return db.get(PlanJob, job_id)


def list_jobs(db: Session) -> list[PlanJob]:
    """List planning jobs newest first."""
    return list(db.scalars(select(PlanJob).order_by(PlanJob.submitted_at.desc())).all())


def cancel_job(db: Session, job_id: uuid.UUID) -> PlanJob:
    """Cancel a queued or running planning job."""
    job = db.get(PlanJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="plan job not found")
    if job.state not in (JobState.QUEUED, JobState.RUNNING):
        raise HTTPException(status_code=409, detail=f"cannot cancel job in state {job.state.value}")
    job.state = JobState.CANCELLED
    job.finished_at = utcnow()
    db.commit()
    db.refresh(job)
    return job


def get_proposal(db: Session, proposal_id: uuid.UUID) -> ScheduleProposal | None:
    """Fetch a schedule proposal by identifier."""
    return db.get(ScheduleProposal, proposal_id)


def list_proposals(db: Session, job_id: uuid.UUID) -> list[ScheduleProposal]:
    """List alternative proposals produced by a planning job."""
    return list(
        db.scalars(
            select(ScheduleProposal)
            .where(ScheduleProposal.plan_job_id == job_id)
            .order_by(ScheduleProposal.created_at, ScheduleProposal.id)
        ).all()
    )


def list_assignments(db: Session, proposal_id: uuid.UUID) -> list[ScheduleAssignment]:
    """List assignments belonging to a proposal."""
    return list(
        db.scalars(
            select(ScheduleAssignment)
            .where(ScheduleAssignment.proposal_id == proposal_id)
            .order_by(ScheduleAssignment.window_start)
        ).all()
    )


def invalidate_proposal(
    db: Session, proposal_id: uuid.UUID, trigger: str, reason: str | None = None
) -> PlanInvalidation:
    """Record an invalidation and enqueue replanning for remaining work."""
    proposal = db.get(ScheduleProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")

    proposal.state = ProposalState.INVALIDATED
    invalidation = PlanInvalidation(
        proposal_id=proposal.id,
        trigger=trigger,
        reason=reason,
        detected_at=utcnow(),
    )
    db.add(invalidation)

    # TODO(RPL-01): completed assignments are preserved; only open work is replanned.
    open_work_package_ids: list[str] = []
    for assignment in list_assignments(db, proposal.id):
        work_package = db.get(WorkPackage, assignment.work_package_id)
        if work_package is None:
            continue
        if work_package.state not in (WorkPackageState.COMPLETED, WorkPackageState.CANCELLED):
            open_work_package_ids.append(str(work_package.id))
    open_work_package_ids = list(dict.fromkeys(open_work_package_ids))

    original = proposal.plan_job.request if proposal.plan_job is not None else {}
    horizon_start = original.get("horizon_start") if isinstance(original, dict) else None
    horizon_end = original.get("horizon_end") if isinstance(original, dict) else None
    now = utcnow()
    replan_job = PlanJob(
        state=JobState.QUEUED,
        submitted_at=now,
        time_limit_seconds=get_settings().solver_time_limit_seconds,
        request={
            "work_package_ids": open_work_package_ids,
            "horizon_start": horizon_start or _iso(now),
            "horizon_end": horizon_end or _iso(now + timedelta(days=7)),
            "notes": f"replan of proposal {proposal.id}",
            "replan_of": str(proposal.id),
            "trigger": trigger,
            "alternatives": original.get("alternatives", 1),
            "objective_profile": original.get("objective_profile", "balanced"),
            "constraints": original.get("constraints", {}),
        },
    )
    db.add(replan_job)
    db.commit()
    db.refresh(invalidation)
    db.refresh(replan_job)
    get_queue().enqueue(replan_job.id)
    invalidation.replan_job_id = replan_job.id
    return invalidation
