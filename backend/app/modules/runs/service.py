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
from app.domain.schemas import ActivityExplanation, ActivitySpanRead, ScenarioJobCreate
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
        "activity_spans": {
            activity_id: ActivitySpanRead(
                occupied_locations=list(activity.occupied_locations),
                closure_locations=list(activity.closure_locations),
                mirrored_locations=list(activity.mirrored_locations),
                interchange_locations=list(activity.interchange_locations),
            )
            for activity_id, activity in sorted(compiled.activities.items())
        },
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


def list_jobs(db: Session, run_id) -> list[ScenarioJob]:
    """List a run's jobs newest first, scoped to the run."""

    run = get_run(db, run_id)
    return list(
        db.scalars(
            select(ScenarioJob)
            .where(ScenarioJob.run_id == run.id)
            .order_by(
                ScenarioJob.submitted_at.desc(),
                ScenarioJob.created_at.desc(),
                ScenarioJob.id.desc(),
            )
        ).all()
    )


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


def _explanation_summary(
    activity_id: str,
    codes: list[str],
    first_week: int,
    planned_start_week: int | None,
    predecessor_activity_id: str | None,
    predecessor_last_week: int | None,
    horizon_weeks: int,
) -> str:
    """Render deterministic prose from the persisted evidence only."""

    parts = [f"first access week {first_week}"]
    if planned_start_week is not None:
        parts.append(f"planned start week {planned_start_week}")
    if first_week > horizon_weeks:
        parts.append(f"beyond nominal horizon of {horizon_weeks} weeks")
    if (
        "PREDECESSOR" in codes
        and predecessor_activity_id is not None
        and predecessor_last_week is not None
    ):
        parts.append(
            f"predecessor {predecessor_activity_id} last access week "
            f"{predecessor_last_week}"
        )
    if "PLANNED_START" in codes:
        parts.append("bounded by planned start")
    if "ECLO_WINDOW" in codes:
        parts.append("ECLO kept within the scenario window")
    if "BUFFER_CLOSURE" in codes:
        parts.append("bounded by a closure buffer")
    if "LIVE_MIRROR" in codes:
        parts.append("Live working mirrored onto the opposite bound")
    if "INTERCHANGE" in codes:
        parts.append("reached the H01-H02 interchange")
    if "POSSESSION_MIX" in codes:
        parts.append("packed under possession-mix rules")
    if "CO_SHARE_PACKED" in codes:
        parts.append("packed into a co-shared possession")
    if "CAPACITY" in codes:
        parts.append("used a location at its capacity limit")
    if "WEEKLY_CAP" in codes:
        parts.append("used the contract weekly access limit")
    if "WORKFRONT" in codes:
        parts.append("used the contract workfront limit")
    if "PRIORITY_OVERRUN" in codes:
        parts.append("contributed to priority-weighted overrun")
    return f"{activity_id} " + "; ".join(parts) + "."


def _activity_evidence(
    codes: list[str],
    activity,
    occupancy_rows: list,
    group_members: dict[tuple[str, int, str], set[str]],
    groups_at_location_week: dict[tuple[str, int], set[str]],
    compiled,
) -> dict[str, object]:
    """Structural facts the reason codes justify, or nothing when unproven.

    Every value is derived from persisted schedule rows and the recompiled
    instance. Codes with no derivable fact add no keys, so the panel degrades to
    the bare reason code instead of inventing a cause.
    """

    evidence: dict[str, object] = {}
    if activity is not None and (
        "POSSESSION_MIX" in codes or "CO_SHARE_PACKED" in codes
    ):
        evidence["access_type"] = activity.access_type

    if "CAPACITY" in codes and occupancy_rows:
        at_limit = []
        for location_id, week, _ in sorted(
            {(row.location_id, row.week, row.co_share_group) for row in occupancy_rows}
        ):
            used = len(groups_at_location_week.get((location_id, week), ()))
            capacity = compiled.location_capacities.get(location_id, 0)
            if capacity and used >= capacity:
                at_limit.append((location_id, week, used, capacity))
        if at_limit:
            location_id, week, used, capacity = at_limit[0]
            evidence["capacity_location"] = location_id
            evidence["capacity_week"] = week
            evidence["capacity_used"] = used
            evidence["capacity_limit"] = capacity

    if "CO_SHARE_PACKED" in codes:
        shared: list[tuple[str, tuple[str, ...]]] = []
        for row in occupancy_rows:
            key = (row.location_id, row.week, row.co_share_group)
            members = group_members.get(key, set())
            if len(members) > 1:
                shared.append((row.co_share_group, tuple(sorted(members))))
        if shared:
            group, members = sorted(shared)[0]
            evidence["co_share_group"] = group
            evidence["co_share_partners"] = list(members)
            evidence["co_share_size"] = len(members)

    if "POSSESSION_MIX" in codes and occupancy_rows:
        groups = sorted(
            {row.co_share_group for row in occupancy_rows if row.co_share_group}
        )
        if groups:
            evidence["mix_groups"] = groups

    if activity is not None:
        if "BUFFER_CLOSURE" in codes:
            evidence["buffer_sectors"] = activity.buffer_sectors
            evidence["closure_location_count"] = len(activity.closure_locations)
        if "LIVE_MIRROR" in codes:
            evidence["opposite_bound_required"] = activity.opposite_bound_required
            evidence["mirrored_location_count"] = len(activity.mirrored_locations)
        if "INTERCHANGE" in codes:
            evidence["interchange_location_count"] = len(activity.interchange_locations)

    return evidence


def _build_explanations(
    db: Session, job: ScenarioJob, access, occupancy
) -> list[ActivityExplanation]:
    """Derive per-activity explanations from persisted evidence, no new table.

    Reason codes are copied verbatim from ``job.result["binding_reasons"]``.
    Evidence is rebuilt from the persisted access and occupancy rows plus the
    recompiled instance, so it survives a worker restart and never invents a
    fact the schedule cannot support.
    """

    result = job.result or {}
    reasons_by_activity = result.get("binding_reasons") or {}
    access_by_activity: dict[str, list] = {}
    for row in access:
        access_by_activity.setdefault(row.activity_id, []).append(row)

    occupancy_by_activity: dict[str, list] = {}
    group_members: dict[tuple[str, int, str], set[str]] = {}
    groups_at_location_week: dict[tuple[str, int], set[str]] = {}
    for row in occupancy:
        occupancy_by_activity.setdefault(row.activity_id, []).append(row)
        group_members.setdefault(
            (row.location_id, row.week, row.co_share_group), set()
        ).add(row.activity_id)
        groups_at_location_week.setdefault((row.location_id, row.week), set()).add(
            row.co_share_group
        )

    if not access_by_activity:
        return []

    run = db.get(PlanningRun, job.run_id)
    if run is None:
        return []
    compiled = compile_instance(instance_for_run(run))
    horizon_weeks = compiled.instance.horizon_weeks

    explanations: list[ActivityExplanation] = []
    for activity_id in sorted(access_by_activity):
        weeks = sorted(row.week for row in access_by_activity[activity_id])
        first_week = weeks[0]
        activity = compiled.activities.get(activity_id)
        predecessor_id = activity.predecessor_activity_id if activity else None
        predecessor_last_week = None
        if predecessor_id is not None:
            predecessor_rows = access_by_activity.get(predecessor_id)
            if predecessor_rows:
                predecessor_last_week = max(row.week for row in predecessor_rows)
        planned_start_week = max(1, activity.planned_start_week) if activity else None
        codes = sorted(set(reasons_by_activity.get(activity_id, [])))
        evidence: dict[str, object] = {
            "first_week": first_week,
            "planned_start_week": planned_start_week,
            "predecessor_activity_id": predecessor_id,
            "predecessor_last_week": predecessor_last_week,
            "horizon_weeks": horizon_weeks,
            "horizon_extended": first_week > horizon_weeks,
        }
        evidence.update(
            _activity_evidence(
                codes,
                activity,
                occupancy_by_activity.get(activity_id, []),
                group_members,
                groups_at_location_week,
                compiled,
            )
        )
        explanations.append(
            ActivityExplanation(
                activity_id=activity_id,
                reason_codes=codes,
                summary=_explanation_summary(
                    activity_id,
                    codes,
                    first_week,
                    planned_start_week,
                    predecessor_id,
                    predecessor_last_week,
                    horizon_weeks,
                ),
                evidence=evidence,
            )
        )
    return explanations


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
    physical_checks = (job.result or {}).get("physical_checks")
    return {
        "run_id": job.run_id,
        "job_id": job.id,
        "scenario": job.scenario,
        "access": access,
        "occupancy": occupancy,
        "results": results,
        "explanations": _build_explanations(db, job, access, occupancy),
        "physical_checks": physical_checks,
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
    "list_jobs",
    "list_runs",
]
