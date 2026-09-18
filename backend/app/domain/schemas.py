"""Pydantic v2 request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    ApprovalDecision,
    ComponentType,
    ConditionTrend,
    DataQualityState,
    FindingType,
    InterventionPriority,
    JobState,
    ModelApprovalState,
    ProposalState,
    RecommendationClass,
    UserRole,
    WorkPackageState,
)


class ReadModel(BaseModel):
    """Base for read schemas bound to ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str
    role: UserRole
    full_name: str | None = None


class UserRead(ReadModel):
    id: uuid.UUID
    username: str
    role: UserRole
    full_name: str | None = None
    created_at: datetime


class AssetCreate(BaseModel):
    fleet: str
    label: str
    asset_type: str
    source_system: str | None = None
    source_id: str | None = None


class AssetRead(ReadModel):
    id: uuid.UUID
    fleet: str
    label: str
    asset_type: str
    source_system: str | None = None
    source_id: str | None = None
    created_at: datetime


class ComponentCreate(BaseModel):
    asset_id: uuid.UUID
    component_type: ComponentType
    serial: str | None = None


class ComponentRead(ReadModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    component_type: ComponentType
    serial: str | None = None
    created_at: datetime


class ConditionEventCreate(BaseModel):
    component_id: uuid.UUID
    score: float
    detected_at: datetime | None = None
    trend: ConditionTrend = ConditionTrend.UNKNOWN
    data_quality: DataQualityState = DataQualityState.CURRENT
    model_version_id: uuid.UUID | None = None
    evidence: dict | None = None


class ConditionEventRead(ReadModel):
    id: uuid.UUID
    component_id: uuid.UUID
    detected_at: datetime
    score: float
    trend: ConditionTrend
    data_quality: DataQualityState
    model_version_id: uuid.UUID | None = None
    evidence: dict | None = None
    created_at: datetime


class AssessmentCreate(BaseModel):
    condition_event_id: uuid.UUID
    recommendation: RecommendationClass
    priority: InterventionPriority
    horizon_hours: int | None = None
    rationale: dict | None = None
    assessed_at: datetime | None = None


class AssessmentRead(ReadModel):
    id: uuid.UUID
    condition_event_id: uuid.UUID
    recommendation: RecommendationClass
    priority: InterventionPriority
    horizon_hours: int | None = None
    rationale: dict | None = None
    assessed_at: datetime
    created_at: datetime


class WorkPackageCreate(BaseModel):
    assessment_id: uuid.UUID
    asset_id: uuid.UUID
    component_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    recommended_action: str | None = None
    priority: InterventionPriority
    state: WorkPackageState = WorkPackageState.CREATED
    competency: str | None = None
    est_duration_min: int | None = None
    tools: list | None = None
    parts: list | None = None


class WorkPackageRead(ReadModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    asset_id: uuid.UUID
    component_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    recommended_action: str | None = None
    priority: InterventionPriority
    state: WorkPackageState
    competency: str | None = None
    est_duration_min: int | None = None
    tools: list | None = None
    parts: list | None = None
    assigned_technician_id: uuid.UUID | None = None
    assigned_crew_id: uuid.UUID | None = None
    created_at: datetime


class PlanningTimeRange(BaseModel):
    """Unavailable interval supplied in a planning resource snapshot."""

    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class PlanningConstraintSnapshot(BaseModel):
    """Point-in-time external constraints attached to a planning job."""

    crew_unavailability: dict[uuid.UUID, list[PlanningTimeRange]] = Field(
        default_factory=dict
    )
    asset_unavailability: dict[uuid.UUID, list[PlanningTimeRange]] = Field(
        default_factory=dict
    )
    depot_parts: dict[uuid.UUID, dict[str, int]] = Field(default_factory=dict)
    depot_tools: dict[uuid.UUID, dict[str, int]] = Field(default_factory=dict)
    crew_regular_minutes: dict[uuid.UUID, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        quantities = [
            quantity
            for inventory in (*self.depot_parts.values(), *self.depot_tools.values())
            for quantity in inventory.values()
        ]
        if any(quantity < 0 for quantity in quantities):
            raise ValueError("resource quantities cannot be negative")
        if any(minutes < 0 for minutes in self.crew_regular_minutes.values()):
            raise ValueError("crew regular minutes cannot be negative")
        return self


class PlanJobSubmit(BaseModel):
    work_package_ids: list[uuid.UUID]
    horizon_start: datetime
    horizon_end: datetime
    notes: str | None = None
    alternatives: int = Field(default=1, ge=1, le=3)
    objective_profile: Literal["balanced", "speed", "cost", "workload"] = "balanced"
    constraints: PlanningConstraintSnapshot = Field(
        default_factory=PlanningConstraintSnapshot
    )

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if not self.work_package_ids:
            raise ValueError("at least one work package is required")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("horizon_end must be after horizon_start")
        return self


class PlanJobRead(ReadModel):
    id: uuid.UUID
    state: JobState
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    time_limit_seconds: int | None = None
    request: dict | None = None
    result: dict | None = None
    error: str | None = None
    created_at: datetime


class ScheduleProposalCreate(BaseModel):
    plan_job_id: uuid.UUID
    state: ProposalState = ProposalState.PROPOSED
    summary: dict | None = None


class ScheduleProposalRead(ReadModel):
    id: uuid.UUID
    plan_job_id: uuid.UUID
    state: ProposalState
    summary: dict | None = None
    created_at: datetime


class ScheduleAssignmentCreate(BaseModel):
    proposal_id: uuid.UUID
    work_package_id: uuid.UUID
    crew_id: uuid.UUID | None = None
    depot_id: uuid.UUID | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


class ScheduleAssignmentRead(ReadModel):
    id: uuid.UUID
    proposal_id: uuid.UUID
    work_package_id: uuid.UUID
    crew_id: uuid.UUID | None = None
    depot_id: uuid.UUID | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    created_at: datetime


class ApprovalCreate(BaseModel):
    proposal_id: uuid.UUID | None = None
    work_package_id: uuid.UUID | None = None
    decision: ApprovalDecision
    comment: str | None = None


class ApprovalRead(ReadModel):
    id: uuid.UUID
    proposal_id: uuid.UUID | None = None
    work_package_id: uuid.UUID | None = None
    actor: str
    role: UserRole
    decision: ApprovalDecision
    comment: str | None = None
    decided_at: datetime
    created_at: datetime


class PublishedScheduleCreate(BaseModel):
    proposal_id: uuid.UUID
    approval_id: uuid.UUID
    published_by: str
    published_at: datetime | None = None


class PublishedScheduleRead(ReadModel):
    id: uuid.UUID
    proposal_id: uuid.UUID
    approval_id: uuid.UUID
    published_at: datetime
    published_by: str
    created_at: datetime


class OutcomeCreate(BaseModel):
    work_package_id: uuid.UUID
    finding_type: FindingType
    actual_finding: str | None = None
    actual_duration_min: int | None = None
    parts_used: list | None = None
    condition_event_id: uuid.UUID | None = None


class MaintenanceOutcomeRead(ReadModel):
    id: uuid.UUID
    work_package_id: uuid.UUID
    condition_event_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    finding_type: FindingType
    actual_finding: str | None = None
    actual_duration_min: int | None = None
    parts_used: list | None = None
    recorded_at: datetime
    created_at: datetime


class ModelVersionCreate(BaseModel):
    name: str
    version: str
    fleet: str | None = None
    training_data_ref: str | None = None
    metrics: dict | None = None
    approval_state: ModelApprovalState = ModelApprovalState.CANDIDATE
    registered_at: datetime | None = None


class ModelVersionRead(ReadModel):
    id: uuid.UUID
    name: str
    version: str
    fleet: str | None = None
    training_data_ref: str | None = None
    metrics: dict | None = None
    approval_state: ModelApprovalState
    registered_at: datetime
    created_at: datetime


class DataSourceStateCreate(BaseModel):
    source_id: uuid.UUID
    state: DataQualityState = DataQualityState.MISSING
    last_valid_ts: datetime | None = None
    updated_at: datetime | None = None


class DataSourceStateRead(ReadModel):
    id: uuid.UUID
    source_id: uuid.UUID
    state: DataQualityState
    last_valid_ts: datetime | None = None
    updated_at: datetime
    created_at: datetime


class TelemetryReadingIn(BaseModel):
    source_key: str
    component_id: uuid.UUID | None = None
    component_serial: str | None = None
    ts: datetime
    channel: str
    value: float


class TelemetryReadingCreate(BaseModel):
    component_id: uuid.UUID
    source_id: uuid.UUID | None = None
    ts: datetime
    channel: str
    value: float
    quality: DataQualityState = DataQualityState.CURRENT


class TelemetryReadingRead(ReadModel):
    id: uuid.UUID
    component_id: uuid.UUID
    source_id: uuid.UUID | None = None
    ts: datetime
    channel: str
    value: float
    quality: DataQualityState
    created_at: datetime
