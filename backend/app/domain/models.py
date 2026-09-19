"""Lean SQLAlchemy 2.x persistence models for Rail Access Optimisation.

Natural rail identifiers (``activity_id``, ``contract_number``, ``location_id``)
remain strings. Surrogate persistence keys are UUIDs. The uploaded eight-CSV
instance is stored verbatim as JSON so the worker can re-parse it independently.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import JobState, Scenario


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class IdTimestampMixin:
    """Shared UUID primary key and creation timestamp."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanningRun(IdTimestampMixin, Base):
    """One uploaded eight-CSV planning instance and its parse summary."""

    __tablename__ = "planning_runs"

    name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_files: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_status: Mapped[str] = mapped_column(String, default="OK")
    horizon_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    horizon_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    jobs: Mapped[list[ScenarioJob]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ScenarioJob(IdTimestampMixin, Base):
    """Async solve request for one scenario of one planning run."""

    __tablename__ = "scenario_jobs"
    # Race backstop: at most one active job per (run, scenario). The service
    # also checks before insert; this partial unique index makes concurrent
    # duplicate submissions impossible at the database level.
    __table_args__ = (
        Index(
            "uq_scenario_jobs_active",
            "run_id",
            "scenario",
            unique=True,
            postgresql_where=text("state IN ('QUEUED', 'RUNNING', 'VALIDATING')"),
            sqlite_where=text("state IN ('QUEUED', 'RUNNING', 'VALIDATING')"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planning_runs.id"), index=True
    )
    scenario: Mapped[Scenario] = mapped_column(Enum(Scenario))
    state: Mapped[JobState] = mapped_column(Enum(JobState), default=JobState.QUEUED)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[PlanningRun] = relationship(back_populates="jobs")
    access_rows: Mapped[list[ScheduleAccessRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    occupancy_rows: Mapped[list[ScheduleOccupancyRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    contract_results: Mapped[list[ContractResultRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    validator_report: Mapped[ValidatorReportRow | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class ScheduleAccessRow(IdTimestampMixin, Base):
    """One persisted ``SCHEDULE_ACCESS.csv`` row for a scenario job."""

    __tablename__ = "schedule_access_rows"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenario_jobs.id"), index=True
    )
    activity_id: Mapped[str] = mapped_column(String)
    access_seq: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    eclo: Mapped[bool] = mapped_column(Boolean, default=False)
    access_night: Mapped[int] = mapped_column(Integer)
    physical_night: Mapped[int | None] = mapped_column(Integer, nullable=True)

    job: Mapped[ScenarioJob] = relationship(back_populates="access_rows")


class ScheduleOccupancyRow(IdTimestampMixin, Base):
    """One persisted ``SCHEDULE_OCCUPANCY.csv`` row for a scenario job."""

    __tablename__ = "schedule_occupancy_rows"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenario_jobs.id"), index=True
    )
    activity_id: Mapped[str] = mapped_column(String)
    week: Mapped[int] = mapped_column(Integer)
    location_id: Mapped[str] = mapped_column(String)
    co_share_group: Mapped[str] = mapped_column(String)

    job: Mapped[ScenarioJob] = relationship(back_populates="occupancy_rows")


class ContractResultRow(IdTimestampMixin, Base):
    """One persisted ``RESULTS.csv`` row for a scenario job."""

    __tablename__ = "contract_result_rows"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenario_jobs.id"), index=True
    )
    contract_number: Mapped[str] = mapped_column(String)
    simulated_completion_date: Mapped[date] = mapped_column(Date)
    overrun_days: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped[ScenarioJob] = relationship(back_populates="contract_results")


class ValidatorReportRow(IdTimestampMixin, Base):
    """The independent validator report persisted for one scenario job."""

    __tablename__ = "validator_report_rows"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenario_jobs.id"), unique=True, index=True
    )
    scenario: Mapped[str] = mapped_column(String)
    feasible: Mapped[bool] = mapped_column(Boolean, default=False)
    workload_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    ready_for_submission: Mapped[bool] = mapped_column(Boolean, default=False)
    authority: Mapped[str] = mapped_column(String, default="fallback")
    report: Mapped[dict] = mapped_column(JSON, default=dict)

    job: Mapped[ScenarioJob] = relationship(back_populates="validator_report")


class ReplanRow(IdTimestampMixin, Base):
    """One persisted disruption impact assessment and minimal-churn replan.

    The replan keeps its own placements as JSON rather than reusing the
    schedule-row tables, so a replan never rewrites the three published
    submission CSVs of the source job.
    """

    __tablename__ = "replan_rows"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planning_runs.id"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenario_jobs.id"), index=True
    )
    scenario: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    safe: Mapped[bool] = mapped_column(Boolean, default=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    churn_cost: Mapped[int] = mapped_column(Integer, default=0)
    disruption: Mapped[list] = mapped_column(JSON, default=list)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(IdTimestampMixin, Base):
    """Generic, authoritative audit trail of significant actions."""

    __tablename__ = "audit_logs"

    actor: Mapped[str] = mapped_column(String, default="system")
    action: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CalendarVersion(IdTimestampMixin, Base):
    """Immutable projection of one assured witness; publishing adds date bindings."""

    __tablename__ = "calendar_versions"
    __table_args__ = (
        Index(
            "uq_calendar_published",
            "run_id",
            "scenario",
            unique=True,
            sqlite_where=text("state = 'PUBLISHED'"),
            postgresql_where=text("state = 'PUBLISHED'"),
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scenario_jobs.id"), unique=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_runs.id"), index=True)
    scenario: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="DRAFT")
    witness_hash: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict] = mapped_column(JSON)
    date_bindings: Mapped[dict] = mapped_column(JSON, default=dict)
