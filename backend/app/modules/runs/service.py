"""Run, job, schedule, report and export service for the rail pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.domain.enums import JobState
from app.domain.models import (
    ContractResultRow,
    PlanningRun,
    ScenarioJob,
    ScheduleAccessRow,
    ScheduleOccupancyRow,
    ValidatorReportRow,
    utcnow,
)
from app.domain.rail.errors import Issue, RailDataError
from app.domain.schemas import ScenarioJobCreate
from app.modules.compiler import compile_instance, expand_all_routes
from app.modules.export import (
    AccessRow,
    OccupancyRow,
    ResultRow,
    build_bundle,
    export_scenario_zip,
    scenario_archive_name,
)
from app.modules.instance import INSTANCE_FILES, parse_mapping
from app.modules.instance.service import build_planning_instance
from app.modules.runs.queue import get_queue

ACTIVE_STATES = (JobState.QUEUED, JobState.RUNNING, JobState.VALIDATING)
TERMINAL_STATES = (
    JobState.COMPLETED,
    JobState.INFEASIBLE,
    JobState.FAILED,
    JobState.TIMED_OUT,
    JobState.CANCELLED,
)


def _issue_detail(issues: Sequence[Issue]) -> dict:
    """Render structured issues into an actionable 422 detail body."""

    return {
        "message": "invalid planning instance",
        "issues": [
            {
                "file": issue.file,
                "row": issue.row,
                "column": issue.column,
                "value": issue.value,
                "message": issue.message,
            }
            for issue in issues
        ],
    }


def _decode_uploads(uploads: Sequence[tuple[str | None, bytes]]) -> dict[str, str]:
    """Validate the exact eight filenames and decode their contents."""

    issues: list[Issue] = []
    sources: dict[str, str] = {}
    for filename, data in uploads:
        name = Path(filename or "").name
        if name not in INSTANCE_FILES:
            issues.append(Issue("unexpected instance file", file=name))
            continue
        if name in sources:
            issues.append(Issue("duplicate instance file", file=name))
            continue
        try:
            sources[name] = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            issues.append(Issue(f"could not decode as UTF-8: {exc}", file=name))
    for name in INSTANCE_FILES:
        if name not in sources:
            issues.append(Issue("missing required instance file", file=name))
    if issues:
        raise HTTPException(status_code=422, detail=_issue_detail(issues))
    return sources


def _run_summary(instance) -> dict:
    """Build the persisted parse summary from a canonical planning instance."""

    return {
        "files": list(INSTANCE_FILES),
        "counts": {
            "lines": len(instance.lines),
            "stations": len(instance.stations),
            "sectors": len(instance.sectors),
            "locations": len(instance.locations),
            "buffer_rules": len(instance.buffer_rules),
            "contracts": len(instance.contracts),
            "activities": len(instance.activities),
        },
        "horizon_start": instance.horizon_start.isoformat(),
        "horizon_weeks": instance.horizon_weeks,
        "issues": [],
    }


def create_run(
    db: Session,
    uploads: Sequence[tuple[str | None, bytes]],
    *,
    actor: str | None = None,
    name: str | None = None,
) -> PlanningRun:
    """Validate, build and compile the eight uploaded files before persisting."""

    sources = _decode_uploads(uploads)
    try:
        instance = build_planning_instance(parse_mapping(sources))
        compile_instance(instance)
    except RailDataError as exc:
        raise HTTPException(status_code=422, detail=_issue_detail(exc.issues)) from exc

    run = PlanningRun(
        name=name,
        source_files=sources,
        parse_summary=_run_summary(instance),
        parse_status="OK",
        horizon_start=instance.horizon_start,
        horizon_weeks=instance.horizon_weeks,
    )
    db.add(run)
    record_audit(
        db,
        actor=actor or "system",
        action="run.created",
        entity_type="planning_run",
        after={"files": sorted(sources)},
    )
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id) -> PlanningRun:
    """Fetch a planning run or raise 404."""

    run = db.get(PlanningRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="planning run not found")
    return run


def list_runs(db: Session) -> list[PlanningRun]:
    """List planning runs newest first."""

    return list(
        db.scalars(select(PlanningRun).order_by(PlanningRun.created_at.desc())).all()
    )


def instance_for_run(run: PlanningRun):
    """Re-parse and build the canonical instance stored on a run."""

    return build_planning_instance(parse_mapping(run.source_files))


def get_network(db: Session, run_id) -> dict:
    """Return the parsed network and expanded routes for a run."""

    run = get_run(db, run_id)
    instance = instance_for_run(run)
    compiled = compile_instance(instance)
    routes = expand_all_routes(instance)

    return {
        "parameters": instance.parameters.model_dump(mode="json"),
        "lines": [line.model_dump(mode="json") for line in instance.lines.values()],
        "stations": [
            station.model_dump(mode="json") for station in instance.stations.values()
        ],
        "sectors": [sector.model_dump(mode="json") for sector in instance.sectors.values()],
        "locations": [
            location.model_dump(mode="json") for location in instance.locations.values()
        ],
        "buffer_rules": [
            rule.model_dump(mode="json") for rule in instance.buffer_rules.values()
        ],
        "contracts": [
            contract.model_dump(mode="json") for contract in instance.contracts.values()
        ],
        "activities": [
            activity.model_dump(mode="json") for activity in instance.activities.values()
        ],
        "routes": {
            activity_id: list(route.location_ids)
            for activity_id, route in routes.items()
        },
        "location_capacities": dict(compiled.location_capacities),
    }


def create_job(
    db: Session, run_id, data: ScenarioJobCreate, *, actor: str | None = None
) -> ScenarioJob:
    """Queue a scenario solve job, rejecting a duplicate active run/scenario."""

    run = get_run(db, run_id)
    duplicate = db.scalar(
        select(ScenarioJob).where(
            ScenarioJob.run_id == run.id,
            ScenarioJob.scenario == data.scenario,
            ScenarioJob.state.in_(ACTIVE_STATES),
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"scenario {data.scenario.value} already has an active job "
                f"({duplicate.id}) for this run"
            ),
        )

    settings = get_settings()
    job = ScenarioJob(
        run_id=run.id,
        scenario=data.scenario,
        state=JobState.QUEUED,
        request={"scenario": data.scenario.value, "actor": actor},
        time_limit_seconds=data.time_limit_seconds or settings.solver_time_limit_seconds,
        seed=data.seed if data.seed is not None else settings.solver_seed,
        submitted_at=utcnow(),
    )
    db.add(job)
    record_audit(
        db,
        actor=actor or "system",
        action="job.created",
        entity_type="scenario_job",
        after={"run_id": str(run.id), "scenario": data.scenario.value},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        # Partial unique index fired: a concurrent request already created an
        # active job for this (run, scenario).
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"scenario {data.scenario.value} already has an active job "
                "for this run"
            ),
        ) from exc
    db.refresh(job)
    get_queue().enqueue(job.id)
    return job


def get_job(db: Session, run_id, job_id) -> ScenarioJob:
    """Fetch a job scoped to its run or raise 404."""

    job = db.get(ScenarioJob, job_id)
    if job is None or job.run_id != run_id:
        raise HTTPException(status_code=404, detail="scenario job not found")
    return job


def cancel_job(db: Session, run_id, job_id, *, actor: str | None = None) -> ScenarioJob:
    """Best-effort cancellation of a queued or running job."""

    job = get_job(db, run_id, job_id)
    if job.state in TERMINAL_STATES:
        raise HTTPException(
            status_code=409, detail=f"cannot cancel job in state {job.state.value}"
        )
    job.cancel_requested = True
    if job.state == JobState.QUEUED:
        job.state = JobState.CANCELLED
        job.finished_at = utcnow()
    record_audit(
        db,
        actor=actor or "system",
        action="job.cancelled",
        entity_type="scenario_job",
        entity_id=str(job.id),
    )
    db.commit()
    db.refresh(job)
    return job


def get_schedule(db: Session, run_id, job_id) -> dict:
    """Return persisted placements and results, or 409 until completion."""

    job = get_job(db, run_id, job_id)
    if job.state != JobState.COMPLETED:
        raise HTTPException(status_code=409, detail="job has not completed")
    access = list(
        db.scalars(
            select(ScheduleAccessRow)
            .where(ScheduleAccessRow.job_id == job.id)
            .order_by(
                ScheduleAccessRow.activity_id,
                ScheduleAccessRow.access_seq,
            )
        ).all()
    )
    occupancy = list(
        db.scalars(
            select(ScheduleOccupancyRow)
            .where(ScheduleOccupancyRow.job_id == job.id)
            .order_by(
                ScheduleOccupancyRow.activity_id,
                ScheduleOccupancyRow.week,
                ScheduleOccupancyRow.location_id,
            )
        ).all()
    )
    results = list(
        db.scalars(
            select(ContractResultRow)
            .where(ContractResultRow.job_id == job.id)
            .order_by(ContractResultRow.contract_number)
        ).all()
    )
    return {
        "run_id": job.run_id,
        "job_id": job.id,
        "scenario": job.scenario,
        "access": access,
        "occupancy": occupancy,
        "results": results,
    }


def get_report(db: Session, run_id, job_id) -> ValidatorReportRow:
    """Return the persisted validator report or 409 when absent."""

    job = get_job(db, run_id, job_id)
    report = db.scalar(
        select(ValidatorReportRow).where(ValidatorReportRow.job_id == job.id)
    )
    if report is None:
        raise HTTPException(status_code=409, detail="validator report is not available")
    return report


def _bundle_for_job(db: Session, job: ScenarioJob):
    """Rebuild the exact submission bundle from persisted rows."""

    access = [
        AccessRow(
            activity_id=row.activity_id,
            access_seq=row.access_seq,
            week=row.week,
            eclo=1 if row.eclo else 0,
            access_night=row.access_night,
        )
        for row in db.scalars(
            select(ScheduleAccessRow).where(ScheduleAccessRow.job_id == job.id)
        ).all()
    ]
    occupancy = [
        OccupancyRow(
            activity_id=row.activity_id,
            week=row.week,
            location_id=row.location_id,
            co_share_group=row.co_share_group,
        )
        for row in db.scalars(
            select(ScheduleOccupancyRow).where(ScheduleOccupancyRow.job_id == job.id)
        ).all()
    ]
    results = [
        ResultRow(
            scenario=job.scenario.value,
            contract_number=row.contract_number,
            simulated_completion_date=row.simulated_completion_date,
            overrun_days=max(0, row.overrun_days),
        )
        for row in db.scalars(
            select(ContractResultRow).where(ContractResultRow.job_id == job.id)
        ).all()
    ]
    return build_bundle(job.scenario.value, access, occupancy, results)


def get_export(db: Session, run_id, job_id) -> tuple[str, bytes]:
    """Return ``(filename, zip_bytes)`` when the submission gate has passed."""

    report = get_report(db, run_id, job_id)
    if not report.ready_for_submission:
        raise HTTPException(
            status_code=409,
            detail="submission gate has not passed for this job",
        )
    job = get_job(db, run_id, job_id)
    payload = export_scenario_zip(_bundle_for_job(db, job))
    return scenario_archive_name(job.scenario.value), payload


__all__ = [
    "ACTIVE_STATES",
    "TERMINAL_STATES",
    "cancel_job",
    "create_job",
    "create_run",
    "get_export",
    "get_job",
    "get_network",
    "get_report",
    "get_run",
    "get_schedule",
    "instance_for_run",
    "list_runs",
]
