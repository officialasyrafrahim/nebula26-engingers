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
from app.modules.solver import reasons
from app.modules.solver.possession import truly_co_sharable

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
    try:
        get_queue().enqueue(job.id)
    except Exception as exc:
        # The database is the authority for job state. A transport failure must
        # not leave the job looking queued forever.
        job.state = JobState.FAILED
        job.error = f"could not enqueue job: {exc}"
        job.finished_at = utcnow()
        db.commit()
        raise HTTPException(
            status_code=503,
            detail=f"could not enqueue scenario job {job.id}: {exc}",
        ) from exc
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


def _binding_label(code: str) -> str:
    """Human phrase for a constraint that rejected an earlier week."""

    return {
        "CAPACITY": "capacity pressure",
        "WEEKLY_CAP": "the contract weekly access cap",
        "WORKFRONT": "the contract workfront limit",
        "BUFFER_CLOSURE": "a closure buffer",
        "LIVE_MIRROR": "Live opposite-bound mirroring",
        "INTERCHANGE": "an interchange closure",
        "POSSESSION_MIX": "possession-mix rules",
    }.get(code, code)


def _explanation_summary(
    activity_id: str,
    codes: list[str],
    first_week: int,
    planned_start_week: int | None,
    predecessor_activity_id: str | None,
    predecessor_last_week: int | None,
    horizon_weeks: int,
    displacement: dict | None = None,
) -> str:
    """Render deterministic prose from the persisted evidence only.

    A cause is only claimed when the persisted displacement evidence names the
    earlier rejected week and the binding constraint. Capacity, weekly-cap and
    workfront phrases are withheld otherwise, so the prose never states a cause
    the schedule cannot support.
    """

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
        parts.append("kept on a separate physical slot by a closure buffer")
    if "LIVE_MIRROR" in codes:
        parts.append("kept separate by Live opposite-bound mirroring")
    if "INTERCHANGE" in codes:
        parts.append("kept separate by an interchange closure")
    if "POSSESSION_MIX" in codes:
        parts.append("packed under possession-mix rules")
    if "CO_SHARE_PACKED" in codes:
        parts.append("packed into a co-shared possession")
    binding = set((displacement or {}).get("binding_constraints") or ())
    if "CAPACITY" in codes and "CAPACITY" in binding:
        parts.append("used a location at its capacity limit")
    if "WEEKLY_CAP" in codes and "WEEKLY_CAP" in binding:
        parts.append("used the contract weekly access limit")
    if "WORKFRONT" in codes and "WORKFRONT" in binding:
        parts.append("used the contract workfront limit")
    if "PRIORITY_OVERRUN" in codes:
        parts.append("contributed to priority-weighted overrun")
    if displacement and displacement.get("displaced"):
        rejected_week = displacement.get("binding_week")
        labels = [
            _binding_label(code)
            for code in displacement.get("binding_constraints", [])
        ]
        if rejected_week is not None and labels:
            parts.append(
                f"earliest start week {displacement.get('planned_earliest_week')} "
                f"blocked at week {rejected_week} by " + " and ".join(labels)
            )
    return f"{activity_id} " + "; ".join(parts) + "."


def _possession_conflict_facts(
    compiled,
    weeks_by_activity: dict[str, set[int]],
) -> dict[str, list[dict[str, object]]]:
    """Counterpart facts for each pair-level possession code.

    The closure codes are assigned to both activities in a conflict, so an
    activity affected by another's Live mirror or interchange can have empty
    spans of its own. Recording the counterpart's facts lets the explanation
    cite the conflict without presenting the own-activity zeros as support.
    """

    facts: dict[str, list[dict[str, object]]] = {}
    for (left_id, right_id), conflict in sorted(
        compiled.physical_possession.closure_conflicts.items()
    ):
        if truly_co_sharable(compiled, left_id, right_id):
            continue
        if not (
            weeks_by_activity.get(left_id, set())
            & weeks_by_activity.get(right_id, set())
        ):
            continue
        code = reasons.CLOSURE_RULE_CODES.get(conflict.rule)
        if code is None:
            continue
        for own_id, other_id in ((left_id, right_id), (right_id, left_id)):
            other = compiled.activities[other_id]
            facts.setdefault(own_id, []).append(
                {
                    "code": code,
                    "counterpart_activity_id": other_id,
                    "counterpart_access_type": other.access_type,
                    "counterpart_opposite_bound_required": other.opposite_bound_required,
                    "counterpart_mirrored_location_count": len(
                        other.mirrored_locations
                    ),
                    "counterpart_interchange_location_count": len(
                        other.interchange_locations
                    ),
                    "counterpart_closure_location_count": len(other.closure_locations),
                    "conflict_locations": sorted(conflict.locations),
                }
            )
    return facts


def _activity_evidence(
    codes: list[str],
    activity,
    occupancy_rows: list,
    group_members: dict[tuple[str, int, str], set[str]],
    compiled,
    conflict_facts: list[dict[str, object]] | None = None,
    displacement: dict | None = None,
) -> dict[str, object]:
    """Structural facts the reason codes justify, or nothing when unproven.

    Every value is derived from persisted schedule rows, the persisted
    displacement evidence and the recompiled instance. Codes with no derivable
    fact add no keys, so the panel degrades to the bare reason code instead of
    inventing a cause. Own spans are only reported when they actually support the
    code; pair-level conflicts carry the counterpart's facts instead.
    """

    evidence: dict[str, object] = {}
    if activity is not None and (
        "POSSESSION_MIX" in codes or "CO_SHARE_PACKED" in codes
    ):
        evidence["access_type"] = activity.access_type

    if "CAPACITY" in codes and displacement and displacement.get("displaced"):
        detail = (displacement.get("binding_details") or {}).get("CAPACITY")
        if detail:
            evidence["capacity_location"] = detail.get("location_id")
            evidence["capacity_week"] = detail.get("week")
            evidence["capacity_used"] = detail.get("used")
            evidence["capacity_limit"] = detail.get("capacity")

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
        if "BUFFER_CLOSURE" in codes and activity.closure_locations:
            evidence["buffer_sectors"] = activity.buffer_sectors
            evidence["closure_location_count"] = len(activity.closure_locations)
        if "LIVE_MIRROR" in codes and activity.mirrored_locations:
            evidence["opposite_bound_required"] = activity.opposite_bound_required
            evidence["mirrored_location_count"] = len(activity.mirrored_locations)
        if "INTERCHANGE" in codes and activity.interchange_locations:
            evidence["interchange_location_count"] = len(activity.interchange_locations)

    pair_facts = [fact for fact in (conflict_facts or []) if fact.get("code") in codes]
    if pair_facts:
        evidence["possession_conflicts"] = pair_facts

    if displacement is not None:
        evidence["displaced"] = bool(displacement.get("displaced"))
        evidence["planned_earliest_week"] = displacement.get("planned_earliest_week")
        evidence["actual_first_week"] = displacement.get("actual_first_week")
        if displacement.get("displaced"):
            evidence["rejected_weeks"] = displacement.get("rejected_weeks", [])
            evidence["binding_week"] = displacement.get("binding_week")
            evidence["binding_constraints"] = displacement.get(
                "binding_constraints", []
            )
            evidence["binding_details"] = displacement.get("binding_details", {})

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
    for row in occupancy:
        occupancy_by_activity.setdefault(row.activity_id, []).append(row)
        group_members.setdefault(
            (row.location_id, row.week, row.co_share_group), set()
        ).add(row.activity_id)

    if not access_by_activity:
        return []

    run = db.get(PlanningRun, job.run_id)
    if run is None:
        return []
    compiled = compile_instance(instance_for_run(run))
    horizon_weeks = compiled.instance.horizon_weeks
    weeks_by_activity = {
        activity_id: {row.week for row in rows}
        for activity_id, rows in access_by_activity.items()
    }
    conflict_facts = _possession_conflict_facts(compiled, weeks_by_activity)
    displacement_map = (
        result.get("objective_breakdown") or {}
    ).get("displacement_evidence") or {}

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
        displacement = displacement_map.get(activity_id)
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
                compiled,
                conflict_facts.get(activity_id, []),
                displacement,
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
                    displacement,
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
