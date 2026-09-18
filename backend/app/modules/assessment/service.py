"""Assessment service.

ERD requirements: ASM-01, ASM-02, ASM-03, WPK-01.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    EvidenceType,
    InterventionPriority,
    RecommendationClass,
    WorkPackageState,
)
from app.domain.models import Assessment, ConditionEvent, Evidence, WorkPackage

_RULES_VERSION = "asm-rules-v0"
_THRESHOLDS = {"maintain": 0.8, "inspect_high": 0.5, "inspect_medium": 0.3}


class ConditionEventNotFoundError(Exception):
    """Raised when a condition event does not exist."""


class AssessmentNotFoundError(Exception):
    """Raised when an assessment does not exist."""


def _rule(score: float) -> tuple[RecommendationClass, InterventionPriority, int]:
    if score >= 0.8:
        return RecommendationClass.MAINTAIN, InterventionPriority.CRITICAL, 24
    if score >= 0.5:
        return RecommendationClass.INSPECT, InterventionPriority.HIGH, 72
    if score >= 0.3:
        return RecommendationClass.INSPECT, InterventionPriority.MEDIUM, 168
    return RecommendationClass.MONITOR, InterventionPriority.LOW, 720


def assess_condition(db: Session, condition_event_id: uuid.UUID) -> Assessment:
    """Assess a condition and persist a recommendation."""
    # TODO(ASM-01): add asset, fault-history and operational context to the rules.
    event = db.get(ConditionEvent, condition_event_id)
    if event is None:
        raise ConditionEventNotFoundError
    recommendation, priority, horizon = _rule(event.score)
    rationale = {
        "rules_version": _RULES_VERSION,
        "score": event.score,
        "thresholds": _THRESHOLDS,
        "context": "unavailable",
    }
    assessment = Assessment(
        condition_event_id=event.id,
        recommendation=recommendation,
        priority=priority,
        horizon_hours=horizon,
        rationale=rationale,
    )
    db.add(assessment)
    db.flush()
    db.add(
        Evidence(
            assessment_id=assessment.id,
            type=EvidenceType.MODEL_INFERENCE,
            content={
                "rules_version": _RULES_VERSION,
                "score": event.score,
                "recommendation": recommendation.value,
                "priority": priority.value,
                "horizon_hours": horizon,
                "thresholds": _THRESHOLDS,
            },
        )
    )
    db.add(
        Evidence(
            assessment_id=assessment.id,
            type=EvidenceType.OBSERVATION,
            content={
                "condition_event_id": str(event.id),
                "condition_evidence": event.evidence or {},
            },
        )
    )
    db.commit()
    return assessment


def list_assessments(db: Session) -> list[Assessment]:
    """List assessments, newest first."""
    return list(
        db.scalars(select(Assessment).order_by(Assessment.assessed_at.desc())).all()
    )


def get_assessment(db: Session, assessment_id: uuid.UUID) -> Assessment | None:
    """Return one assessment or None when absent."""
    return db.get(Assessment, assessment_id)


def list_evidence(db: Session, assessment_id: uuid.UUID) -> list[Evidence]:
    """List evidence rows attached to an assessment."""
    return list(
        db.scalars(
            select(Evidence)
            .where(Evidence.assessment_id == assessment_id)
            .order_by(Evidence.created_at)
        ).all()
    )


def create_work_package(
    db: Session,
    assessment_id: uuid.UUID,
    title: str | None = None,
    recommended_action: str | None = None,
) -> WorkPackage:
    """Create a work package for an actionable assessment."""
    # TODO(WPK-01): competency, duration, tools and parts stay unavailable.
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError
    event = assessment.condition_event
    component = event.component
    asset = component.asset
    default_title = (
        f"{assessment.recommendation.value} maintenance for {component.component_type.value}"
    )
    work_package = WorkPackage(
        assessment_id=assessment.id,
        asset_id=asset.id,
        component_id=component.id,
        title=title or default_title,
        recommended_action=recommended_action,
        priority=assessment.priority,
        state=WorkPackageState.CREATED,
    )
    db.add(work_package)
    db.commit()
    return work_package


def list_work_packages(db: Session) -> list[WorkPackage]:
    """List work packages, newest first."""
    return list(db.scalars(select(WorkPackage).order_by(WorkPackage.created_at.desc())).all())


def get_work_package(db: Session, work_package_id: uuid.UUID) -> WorkPackage | None:
    """Return one work package or None when absent."""
    return db.get(WorkPackage, work_package_id)
