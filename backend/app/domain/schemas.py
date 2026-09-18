"""Pydantic v2 API schemas for the Rail Access Optimisation shell.

Natural rail identifiers stay strings. Surrogate persistence ids are UUIDs and
timestamps are ISO-8601 UTC. Read schemas bind directly to ORM objects.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobState, Scenario
from app.modules.validator.witness import PhysicalWitnessReport


class ReadModel(BaseModel):
    """Base for read schemas bound to ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class ParseSummary(BaseModel):
    """Human-readable summary of the eight uploaded instance files."""

    files: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    horizon_start: date | None = None
    horizon_weeks: int | None = None
    issues: list[str] = Field(default_factory=list)


class PlanningRunRead(ReadModel):
    """A persisted planning instance."""

    id: uuid.UUID
    name: str | None = None
    parse_status: str
    parse_summary: dict
    horizon_start: date | None = None
    horizon_weeks: int | None = None
    created_at: datetime


class ActivitySpanRead(BaseModel):
    """Compiled physical spans for one activity on a run.

    Additive control-board contract. Values are compiled from the same instance
    the solver consumes, so consumers never re-derive closure logic.
    """

    model_config = ConfigDict(extra="forbid")

    occupied_locations: list[str] = Field(default_factory=list)
    closure_locations: list[str] = Field(default_factory=list)
    mirrored_locations: list[str] = Field(default_factory=list)
    interchange_locations: list[str] = Field(default_factory=list)


class NetworkResponse(BaseModel):
    """The parsed rail network and expanded routes for one run."""

    parameters: dict
    lines: list[dict]
    stations: list[dict]
    sectors: list[dict]
    locations: list[dict]
    buffer_rules: list[dict]
    contracts: list[dict]
    activities: list[dict]
    routes: dict[str, list[str]]
    location_capacities: dict[str, int]
    activity_spans: dict[str, ActivitySpanRead] = Field(default_factory=dict)


class ScenarioJobCreate(BaseModel):
    """Request body for creating a scenario solve job."""

    scenario: Scenario
    time_limit_seconds: int | None = Field(default=None, gt=0)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)


class ScenarioJobRead(ReadModel):
    """Lifecycle of one asynchronous scenario solve job."""

    id: uuid.UUID
    run_id: uuid.UUID
    scenario: Scenario
    state: JobState
    request: dict
    result: dict | None = None
    error: str | None = None
    cancel_requested: bool = False
    time_limit_seconds: int | None = None
    seed: int | None = None
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ScheduleAccessRead(ReadModel):
    """One persisted access placement."""

    id: uuid.UUID
    activity_id: str
    access_seq: int
    week: int
    eclo: bool
    access_night: int
    physical_night: int | None = None


class ScheduleOccupancyRead(ReadModel):
    """One persisted occupancy placement."""

    id: uuid.UUID
    activity_id: str
    week: int
    location_id: str
    co_share_group: str


class ContractResultRead(ReadModel):
    """One persisted contract completion result."""

    id: uuid.UUID
    contract_number: str
    simulated_completion_date: date
    overrun_days: int


class ActivityExplanation(BaseModel):
    """Deterministic explanation for one activity's first access placement.

    Reason codes are copied from the solver evidence persisted on the job. The
    evidence mapping is recomputed from the persisted schedule and the
    recompiled instance so the explanation survives a process reload.
    """

    activity_id: str
    reason_codes: list[str] = Field(default_factory=list)
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ScheduleResponse(BaseModel):
    """The schedule, occupancy and contract results of a completed job."""

    run_id: uuid.UUID
    job_id: uuid.UUID
    scenario: Scenario
    access: list[ScheduleAccessRead]
    occupancy: list[ScheduleOccupancyRead]
    results: list[ContractResultRead]
    explanations: list[ActivityExplanation] = Field(default_factory=list)
    physical_checks: PhysicalWitnessReport | None = None


class ValidatorReportRead(ReadModel):
    """The independent validator report and its submission gate."""

    id: uuid.UUID
    job_id: uuid.UUID
    scenario: str
    feasible: bool
    workload_complete: bool
    ready_for_submission: bool
    authority: str
    report: dict[str, Any]
    created_at: datetime


__all__ = [
    "ActivityExplanation",
    "ActivitySpanRead",
    "ContractResultRead",
    "NetworkResponse",
    "ParseSummary",
    "PlanningRunRead",
    "ScenarioJobCreate",
    "ScenarioJobRead",
    "ScheduleAccessRead",
    "ScheduleOccupancyRead",
    "ScheduleResponse",
    "ValidatorReportRead",
]
