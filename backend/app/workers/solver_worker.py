"""Standalone solver worker process.

ERD requirements: PLN-04, ARC-01.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.domain.enums import JobState, ProposalState
from app.domain.models import (
    Crew,
    Depot,
    MaintenanceWindow,
    PlanJob,
    ScheduleAssignment,
    ScheduleProposal,
    WorkPackage,
    utcnow,
)
from app.modules.planning.queue import get_queue
from app.modules.planning.solver import PlanRequest, SolverResult, solve_plan


def _ensure_aware(value: datetime | None) -> datetime | None:
    """Attach UTC to naive timestamps so comparisons stay consistent."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO timestamp from a stored request."""
    if not value:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def _parse_uuid(value: object) -> uuid.UUID | None:
    """Parse a UUID-like value, returning None when invalid."""
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _build_plan_request(session: Session, job: PlanJob) -> PlanRequest:
    """Load canonical entities into a solver request."""
    payload = job.request if isinstance(job.request, dict) else {}
    work_package_ids = [
        parsed
        for parsed in (_parse_uuid(raw) for raw in payload.get("work_package_ids", []))
        if parsed
    ]
    work_packages = (
        list(session.scalars(select(WorkPackage).where(WorkPackage.id.in_(work_package_ids))).all())
        if work_package_ids
        else []
    )
    horizon_start = _parse_timestamp(payload.get("horizon_start")) or _ensure_aware(
        job.submitted_at
    )
    horizon_end = _parse_timestamp(payload.get("horizon_end")) or (
        horizon_start + timedelta(days=7)
    )

    windows = list(session.scalars(select(MaintenanceWindow)).all())
    crews = list(session.scalars(select(Crew)).all())
    depots = list(session.scalars(select(Depot)).all())

    return PlanRequest(
        work_packages=[
            {
                "id": str(work_package.id),
                "title": work_package.title,
                "priority": work_package.priority.value,
                "est_duration_min": work_package.est_duration_min or 0,
                "competency": work_package.competency,
            }
            for work_package in work_packages
        ],
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        time_limit_seconds=job.time_limit_seconds or 300,
        crews=[
            {
                "id": str(crew.id),
                "competencies": crew.competencies or [],
                "depot_id": str(crew.depot_id) if crew.depot_id else None,
            }
            for crew in crews
        ],
        windows=[
            {
                "id": str(window.id),
                "depot_id": str(window.depot_id) if window.depot_id else None,
                "starts_at": _ensure_aware(window.starts_at),
                "ends_at": _ensure_aware(window.ends_at),
            }
            for window in windows
            if _ensure_aware(window.ends_at) > horizon_start
            and _ensure_aware(window.starts_at) < horizon_end
        ],
        depots=[
            {"id": str(depot.id), "name": depot.name, "capacity": depot.capacity}
            for depot in depots
        ],
    )


def _persist_proposal(
    session: Session, job: PlanJob, request: PlanRequest, result: SolverResult
) -> ScheduleProposal:
    """Persist a feasible proposal and its assignments."""
    proposal = ScheduleProposal(
        plan_job_id=job.id,
        state=ProposalState.PROPOSED,
        summary={
            **result.objective_breakdown,
            "work_package_count": len(request.work_packages),
            "assignment_count": len(result.assignments),
        },
    )
    session.add(proposal)
    session.flush()

    for assignment in result.assignments:
        session.add(
            ScheduleAssignment(
                proposal_id=proposal.id,
                work_package_id=uuid.UUID(str(assignment["work_package_id"])),
                crew_id=_parse_uuid(assignment.get("crew_id")),
                depot_id=_parse_uuid(assignment.get("depot_id")),
                window_start=assignment.get("window_start"),
                window_end=assignment.get("window_end"),
            )
        )

    job.state = JobState.COMPLETED
    job.result = {
        "objective_breakdown": result.objective_breakdown,
        "proposal_id": str(proposal.id),
        "assignment_count": len(result.assignments),
    }
    return proposal


def _mark_job(
    session: Session,
    job_id: uuid.UUID,
    state: JobState,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Roll back and record a terminal job state."""
    session.rollback()
    job = session.get(PlanJob, job_id)
    if job is None:
        return
    job.state = state
    job.result = result
    job.error = error
    job.finished_at = utcnow()
    session.commit()


def process_next_job(timeout: float | None = 5.0) -> bool:
    """Claim and process the next queued planning job."""
    # TODO(PLN-04): durable queue-backed job processing.
    job_id = get_queue().dequeue(timeout)
    if job_id is None:
        return False

    session = SessionLocal()
    try:
        job = session.get(PlanJob, job_id)
        if job is None or job.state != JobState.QUEUED:
            return True
        job.state = JobState.RUNNING
        job.started_at = utcnow()
        session.commit()

        try:
            request = _build_plan_request(session, job)
            result = solve_plan(request)
        except TimeoutError as exc:
            _mark_job(session, job_id, JobState.TIMED_OUT, error=str(exc))
            return True
        except Exception as exc:
            _mark_job(session, job_id, JobState.FAILED, error=str(exc))
            return True

        if not result.feasible:
            job.state = JobState.INFEASIBLE
            job.result = {"infeasibility_reasons": result.infeasibility_reasons}
            job.finished_at = utcnow()
            session.commit()
            return True

        try:
            _persist_proposal(session, job, request, result)
            job.finished_at = utcnow()
            session.commit()
        except Exception as exc:
            _mark_job(session, job_id, JobState.FAILED, error=str(exc))
    finally:
        session.close()
    return True


def run_worker() -> None:
    """Run the worker loop until interrupted."""
    try:
        while True:
            process_next_job(timeout=1.0)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    run_worker()
