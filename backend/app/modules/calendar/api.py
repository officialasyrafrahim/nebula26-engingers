"""Calendar routes follow the existing run/job namespace."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.modules.calendar import service

router = APIRouter(prefix="/api/v1/runs/{run_id}/jobs/{job_id}/calendar", tags=["calendar"])


class Publication(BaseModel):
    date_bindings: dict[str, date]


@router.get("")
def get_calendar(run_id: UUID, job_id: UUID, db: Session = Depends(get_db)):
    return service.calendar(db, run_id, job_id)


@router.get("/events")
def events(run_id: UUID, job_id: UUID, db: Session = Depends(get_db)):
    return service.calendar(db, run_id, job_id)


@router.post("/publish")
def publish(
    run_id: UUID,
    job_id: UUID,
    data: Publication,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
):
    return service.publish(db, run_id, job_id, data.date_bindings, user.id)


@router.get("/ics")
def ics(run_id: UUID, job_id: UUID, db: Session = Depends(get_db)):
    return Response(
        service.export_ics(db, run_id, job_id),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="rao-{job_id}.ics"'},
    )
