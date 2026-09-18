"""Canonical SQLAlchemy 2.x domain models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import (
    ApprovalDecision,
    ComponentType,
    ConditionTrend,
    DataQualityState,
    EvidenceType,
    FindingType,
    InterventionPriority,
    JobState,
    ModelApprovalState,
    ProposalState,
    RecommendationClass,
    UserRole,
    WorkPackageState,
)


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class IdTimestampMixin:
    """Shared UUID primary key and creation timestamp."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(IdTimestampMixin, Base):
    """Actor identity and role."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)


class Asset(IdTimestampMixin, Base):
    """Canonical train/vehicle/depot unit."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("source_system", "source_id", name="uq_assets_source"),)

    fleet: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    asset_type: Mapped[str] = mapped_column(String)
    source_system: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)

    components: Mapped[list[Component]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class Component(IdTimestampMixin, Base):
    """Maintainable sub-system on an asset."""

    __tablename__ = "components"

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    component_type: Mapped[ComponentType] = mapped_column(Enum(ComponentType))
    serial: Mapped[str | None] = mapped_column(String, nullable=True)

    asset: Mapped[Asset] = relationship(back_populates="components")
    telemetry_readings: Mapped[list[TelemetryReading]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )
    condition_events: Mapped[list[ConditionEvent]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )


class DataSource(IdTimestampMixin, Base):
    """Registered source system or feed."""

    __tablename__ = "data_sources"

    key: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    states: Mapped[list[DataSourceState]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class DataSourceState(IdTimestampMixin, Base):
    """Current freshness/quality of a source."""

    __tablename__ = "data_source_states"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id"))
    state: Mapped[DataQualityState] = mapped_column(
        Enum(DataQualityState), default=DataQualityState.MISSING
    )
    last_valid_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped[DataSource] = relationship(back_populates="states")


class TelemetryReading(IdTimestampMixin, Base):
    """Time-series measurement mapped to a canonical component."""

    __tablename__ = "telemetry_readings"
    # TODO(PERF-01): move to TimescaleDB hypertable after capacity characterization.

    component_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("components.id"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_sources.id"), nullable=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    channel: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    quality: Mapped[DataQualityState] = mapped_column(
        Enum(DataQualityState), default=DataQualityState.CURRENT
    )

    component: Mapped[Component] = relationship(back_populates="telemetry_readings")


class ModelVersion(IdTimestampMixin, Base):
    """Registered model/version metadata and approval state."""

    __tablename__ = "model_versions"
    # TODO(ML-03): fleet-specific registry traceability.

    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    fleet: Mapped[str | None] = mapped_column(String, nullable=True)
    training_data_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approval_state: Mapped[ModelApprovalState] = mapped_column(
        Enum(ModelApprovalState), default=ModelApprovalState.CANDIDATE
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConditionEvent(IdTimestampMixin, Base):
    """Model/detector prediction of a condition."""

    __tablename__ = "condition_events"
    # TODO(DET-01): multivariable detector.

    component_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("components.id"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    score: Mapped[float] = mapped_column(Float)
    trend: Mapped[ConditionTrend] = mapped_column(
        Enum(ConditionTrend), default=ConditionTrend.UNKNOWN
    )
    data_quality: Mapped[DataQualityState] = mapped_column(
        Enum(DataQualityState), default=DataQualityState.CURRENT
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.id"), nullable=True
    )
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)

    component: Mapped[Component] = relationship(back_populates="condition_events")
    assessments: Mapped[list[Assessment]] = relationship(
        back_populates="condition_event", cascade="all, delete-orphan"
    )
    evidence_items: Mapped[list[Evidence]] = relationship(
        back_populates="condition_event", cascade="all, delete-orphan"
    )


class Evidence(IdTimestampMixin, Base):
    """Inspectable support for a condition or assessment."""

    __tablename__ = "evidence"

    condition_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("condition_events.id"), nullable=True
    )
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessments.id"), nullable=True
    )
    type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType))
    content: Mapped[dict] = mapped_column(JSON, default=dict)

    condition_event: Mapped[ConditionEvent | None] = relationship(back_populates="evidence_items")
    assessment: Mapped[Assessment | None] = relationship(back_populates="evidence_items")


class Assessment(IdTimestampMixin, Base):
    """Contextual significance and recommendation."""

    __tablename__ = "assessments"

    condition_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("condition_events.id"))
    recommendation: Mapped[RecommendationClass] = mapped_column(Enum(RecommendationClass))
    priority: Mapped[InterventionPriority] = mapped_column(Enum(InterventionPriority))
    horizon_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rationale: Mapped[dict] = mapped_column(JSON, default=dict)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    condition_event: Mapped[ConditionEvent] = relationship(back_populates="assessments")
    work_packages: Mapped[list[WorkPackage]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    evidence_items: Mapped[list[Evidence]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class WorkPackage(IdTimestampMixin, Base):
    """Actionable maintenance requirement."""

    __tablename__ = "work_packages"
    # TODO(WPK-01): optional fields stay null when unavailable, never invented.

    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessments.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[InterventionPriority] = mapped_column(Enum(InterventionPriority))
    state: Mapped[WorkPackageState] = mapped_column(
        Enum(WorkPackageState), default=WorkPackageState.CREATED
    )
    competency: Mapped[str | None] = mapped_column(String, nullable=True)
    est_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    parts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    assigned_crew_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crews.id"), nullable=True
    )

    assessment: Mapped[Assessment] = relationship(back_populates="work_packages")
    assignments: Mapped[list[ScheduleAssignment]] = relationship(
        back_populates="work_package", cascade="all, delete-orphan"
    )
    outcomes: Mapped[list[MaintenanceOutcome]] = relationship(
        back_populates="work_package", cascade="all, delete-orphan"
    )


class Depot(IdTimestampMixin, Base):
    """Physical maintenance location and capacity."""

    __tablename__ = "depots"

    name: Mapped[str] = mapped_column(String)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    crews: Mapped[list[Crew]] = relationship(back_populates="depot")
    windows: Mapped[list[MaintenanceWindow]] = relationship(back_populates="depot")


class Crew(IdTimestampMixin, Base):
    """Available maintenance crew and competency."""

    __tablename__ = "crews"

    name: Mapped[str] = mapped_column(String)
    competencies: Mapped[list] = mapped_column(JSON, default=list)
    depot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("depots.id"), nullable=True)

    depot: Mapped[Depot | None] = relationship(back_populates="crews")


class MaintenanceWindow(IdTimestampMixin, Base):
    """Allowed maintenance time at a depot."""

    __tablename__ = "maintenance_windows"

    depot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("depots.id"), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    depot: Mapped[Depot | None] = relationship(back_populates="windows")


class PlanJob(IdTimestampMixin, Base):
    """Async optimization request and lifecycle."""

    __tablename__ = "plan_jobs"
    # TODO(PLN-04): durable queue-backed job store.

    state: Mapped[JobState] = mapped_column(Enum(JobState), default=JobState.QUEUED)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    proposals: Mapped[list[ScheduleProposal]] = relationship(
        back_populates="plan_job", cascade="all, delete-orphan"
    )


class ScheduleProposal(IdTimestampMixin, Base):
    """Candidate feasible plan from a job."""

    __tablename__ = "schedule_proposals"

    plan_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_jobs.id"))
    state: Mapped[ProposalState] = mapped_column(
        Enum(ProposalState), default=ProposalState.PROPOSED
    )
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    plan_job: Mapped[PlanJob] = relationship(back_populates="proposals")
    assignments: Mapped[list[ScheduleAssignment]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )
    invalidations: Mapped[list[PlanInvalidation]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )
    published: Mapped[list[PublishedSchedule]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )


class ScheduleAssignment(IdTimestampMixin, Base):
    """Assignment of a work package to crew/depot/time."""

    __tablename__ = "schedule_assignments"

    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_proposals.id"))
    work_package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_packages.id"))
    crew_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crews.id"), nullable=True)
    depot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("depots.id"), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proposal: Mapped[ScheduleProposal] = relationship(back_populates="assignments")
    work_package: Mapped[WorkPackage] = relationship(back_populates="assignments")


class Approval(IdTimestampMixin, Base):
    """Human decision on a proposal or work package."""

    __tablename__ = "approvals"

    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_proposals.id"), nullable=True
    )
    work_package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_packages.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    decision: Mapped[ApprovalDecision] = mapped_column(Enum(ApprovalDecision))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    proposal: Mapped[ScheduleProposal | None] = relationship(back_populates="approvals")


class PublishedSchedule(IdTimestampMixin, Base):
    """Approved schedule released for write-back."""

    __tablename__ = "published_schedules"

    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_proposals.id"))
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_by: Mapped[str] = mapped_column(String)

    proposal: Mapped[ScheduleProposal] = relationship(back_populates="published")


class PlanInvalidation(IdTimestampMixin, Base):
    """Record that a plan was invalidated and why."""

    __tablename__ = "plan_invalidations"
    # TODO(RPL-01): preserve completed work on replan.

    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_proposals.id"))
    trigger: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    proposal: Mapped[ScheduleProposal] = relationship(back_populates="invalidations")


class MaintenanceOutcome(IdTimestampMixin, Base):
    """Actual finding/work performed, linked to the prediction."""

    __tablename__ = "maintenance_outcomes"
    # TODO(FBK-01): insert-only link to originating prediction.

    work_package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_packages.id"))
    condition_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("condition_events.id"), nullable=True
    )
    technician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    finding_type: Mapped[FindingType] = mapped_column(Enum(FindingType))
    actual_finding: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parts_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    work_package: Mapped[WorkPackage] = relationship(back_populates="outcomes")


class AuditLog(IdTimestampMixin, Base):
    """Authoritative audit trail of significant actions."""

    __tablename__ = "audit_logs"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
