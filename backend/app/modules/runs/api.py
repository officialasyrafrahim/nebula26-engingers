"""Rail Access Optimisation API router.

All endpoints live under ``/api/v1``. Uploads are validated, built and compiled
before anything is persisted; solve work is always queued and returns 202.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.domain.schemas import (
    NetworkResponse,
    PlanningRunRead,
    ReplanRead,
    ReplanRequest,
    ScenarioJobCreate,
    ScenarioJobRead,
    ScheduleResponse,
    ValidatorReportRead,
)
from app.modules.runs import service

router = APIRouter(prefix="/api/v1", tags=["runs"])


@router.post(
    "/runs",
    response_model=PlanningRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> PlanningRunRead:
    """Upload exactly the eight instance files and persist a compiled run."""

    uploads = [(upload.filename, await upload.read()) for upload in files]
    return service.create_run(db, uploads, actor=user.id)


@router.get("/runs", response_model=list[PlanningRunRead])
def list_runs(db: Session = Depends(get_db)) -> list[PlanningRunRead]:
    """List planning runs newest first."""

    return service.list_runs(db)


@router.get("/runs/{run_id}", response_model=PlanningRunRead)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> PlanningRunRead:
    """Fetch a planning run and its parse summary."""

    return service.get_run(db, run_id)


@router.get("/runs/{run_id}/network", response_model=NetworkResponse)
def get_network(run_id: uuid.UUID, db: Session = Depends(get_db)) -> NetworkResponse:
    """Return the parsed network and expanded routes for a run."""

    return service.get_network(db, run_id)


@router.post(
    "/runs/{run_id}/jobs",
    response_model=ScenarioJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_job(
    run_id: uuid.UUID,
    data: ScenarioJobCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> ScenarioJobRead:
    """Queue a scenario A/B/C solve and return immediately."""

    return service.create_job(db, run_id, data, actor=user.id)


@router.get("/runs/{run_id}/jobs", response_model=list[ScenarioJobRead])
def list_jobs(run_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ScenarioJobRead]:
    """List a run's jobs newest first."""

    return service.list_jobs(db, run_id)


@router.get("/runs/{run_id}/jobs/{job_id}", response_model=ScenarioJobRead)
def get_job(
    run_id: uuid.UUID, job_id: uuid.UUID, db: Session = Depends(get_db)
) -> ScenarioJobRead:
    """Fetch the lifecycle state of a scenario job."""

    return service.get_job(db, run_id, job_id)


@router.post(
    "/runs/{run_id}/jobs/{job_id}/cancel",
    response_model=ScenarioJobRead,
)
def cancel_job(
    run_id: uuid.UUID,
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> ScenarioJobRead:
    """Best-effort cancellation of a queued or running job."""

    return service.cancel_job(db, run_id, job_id, actor=user.id)


@router.get(
    "/runs/{run_id}/jobs/{job_id}/schedule",
    response_model=ScheduleResponse,
)
def get_schedule(
    run_id: uuid.UUID, job_id: uuid.UUID, db: Session = Depends(get_db)
) -> ScheduleResponse:
    """Return placements, occupancy and contract results for a completed job."""

    return service.get_schedule(db, run_id, job_id)


@router.get(
    "/runs/{run_id}/jobs/{job_id}/report",
    response_model=ValidatorReportRead,
)
def get_report(
    run_id: uuid.UUID, job_id: uuid.UUID, db: Session = Depends(get_db)
) -> ValidatorReportRead:
    """Return the independent validator report for a job."""

    return service.get_report(db, run_id, job_id)


@router.post(
    "/runs/{run_id}/jobs/{job_id}/replan",
    response_model=ReplanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_replan(
    run_id: uuid.UUID,
    job_id: uuid.UUID,
    data: ReplanRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> ReplanRead:
    """Impact-assess a disruption and return a minimal-churn replan and diff."""

    return service.create_replan(db, run_id, job_id, data, actor=user.id)


@router.get("/runs/{run_id}/replans/{replan_id}", response_model=ReplanRead)
def get_replan(
    run_id: uuid.UUID, replan_id: uuid.UUID, db: Session = Depends(get_db)
) -> ReplanRead:
    """Fetch a persisted disruption impact assessment and replan diff."""

    return service.get_replan(db, run_id, replan_id)


@router.get("/runs/{run_id}/jobs/{job_id}/export")
def get_export(
    run_id: uuid.UUID, job_id: uuid.UUID, db: Session = Depends(get_db)
) -> Response:
    """Download the scenario zip when and only when the gate has passed."""

    filename, payload = service.get_export(db, run_id, job_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
