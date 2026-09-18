"""Seed helpers for planning, approval and execution tests."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.domain.enums import (
    ComponentType,
    ConditionTrend,
    DataQualityState,
    EvidenceType,
    InterventionPriority,
    JobState,
    ProposalState,
    RecommendationClass,
    WorkPackageState,
)
from app.domain.models import (
    Assessment,
    Asset,
    Component,
    ConditionEvent,
    Crew,
    Depot,
    Evidence,
    MaintenanceWindow,
    PlanJob,
    ScheduleAssignment,
    ScheduleProposal,
    WorkPackage,
)
from app.modules.planning.queue import get_queue

BASE = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def reset_queue() -> None:
    """Replace the process-wide job queue with a fresh instance."""
    get_queue.cache_clear()


def seed_scenario(
    db: Session,
    *,
    work_packages: list[tuple[str, InterventionPriority, int, str | None]],
    windows: list[tuple[int, int]],
    competencies: tuple[str, ...] = ("mechanical",),
    base: datetime | None = None,
) -> dict:
    """Seed a detection chain, crew, depot and maintenance windows."""
    base = base or BASE
    asset = Asset(fleet="Fleet-A", label="Unit 1001", asset_type="EMU")
    db.add(asset)
    db.flush()

    component = Component(
        asset_id=asset.id, component_type=ComponentType.DOOR_SYSTEM, serial="CMP-1"
    )
    db.add(component)
    db.flush()

    condition_event = ConditionEvent(
        component_id=component.id,
        score=0.91,
        trend=ConditionTrend.DETERIORATING,
        data_quality=DataQualityState.CURRENT,
        evidence={"channel": "vibration"},
    )
    db.add(condition_event)
    db.flush()

    assessment = Assessment(
        condition_event_id=condition_event.id,
        recommendation=RecommendationClass.MAINTAIN,
        priority=InterventionPriority.CRITICAL,
        horizon_hours=24,
        rationale={"note": "elevated vibration trend"},
    )
    db.add(assessment)
    db.flush()

    db.add(
        Evidence(
            assessment_id=assessment.id,
            type=EvidenceType.MODEL_INFERENCE,
            content={"feature": "vibration_rms", "value": 0.91},
        )
    )

    depot = Depot(name="Depot-1", capacity=4)
    db.add(depot)
    db.flush()

    crew = Crew(name="Crew-A", competencies=list(competencies), depot_id=depot.id)
    db.add(crew)
    db.flush()

    created_work_packages = []
    for title, priority, est_duration_min, competency in work_packages:
        work_package = WorkPackage(
            assessment_id=assessment.id,
            asset_id=asset.id,
            component_id=component.id,
            title=title,
            priority=priority,
            state=WorkPackageState.CREATED,
            competency=competency,
            est_duration_min=est_duration_min,
        )
        db.add(work_package)
        created_work_packages.append(work_package)

    created_windows = []
    for start_offset, end_offset in windows:
        window = MaintenanceWindow(
            depot_id=depot.id,
            starts_at=base + timedelta(minutes=start_offset),
            ends_at=base + timedelta(minutes=end_offset),
        )
        db.add(window)
        created_windows.append(window)

    db.commit()
    return {
        "asset": asset,
        "component": component,
        "condition_event": condition_event,
        "assessment": assessment,
        "depot": depot,
        "crew": crew,
        "work_packages": created_work_packages,
        "windows": created_windows,
        "horizon_start": base - timedelta(hours=1),
        "horizon_end": base + timedelta(hours=4),
    }


def plan_payload(scenario: dict, work_packages: list[WorkPackage] | None = None) -> dict:
    """Build a PlanJobSubmit payload from a seeded scenario."""
    selected = work_packages if work_packages is not None else scenario["work_packages"]
    return {
        "work_package_ids": [str(work_package.id) for work_package in selected],
        "horizon_start": scenario["horizon_start"].isoformat(),
        "horizon_end": scenario["horizon_end"].isoformat(),
        "notes": "test plan",
    }


def seed_proposal(db: Session, *, with_assignment: bool = True) -> dict:
    """Seed a completed job and a proposed schedule with one assignment."""
    scenario = seed_scenario(
        db,
        work_packages=[("WP-PROP", InterventionPriority.CRITICAL, 60, "mechanical")],
        windows=[(0, 60)],
    )
    work_package = scenario["work_packages"][0]
    job = PlanJob(
        state=JobState.COMPLETED,
        submitted_at=scenario["horizon_start"],
        time_limit_seconds=30,
        request={"work_package_ids": [str(work_package.id)]},
    )
    db.add(job)
    db.flush()

    proposal = ScheduleProposal(
        plan_job_id=job.id, state=ProposalState.PROPOSED, summary={"makespan_hours": 1.0}
    )
    db.add(proposal)
    db.flush()

    if with_assignment:
        db.add(
            ScheduleAssignment(
                proposal_id=proposal.id,
                work_package_id=work_package.id,
                crew_id=scenario["crew"].id,
                depot_id=scenario["depot"].id,
                window_start=scenario["windows"][0].starts_at,
                window_end=scenario["windows"][0].ends_at,
            )
        )
    db.commit()

    result = dict(scenario)
    result.update({"plan_job": job, "proposal": proposal})
    return result
