"""Pydantic v2 API schemas for the Rail Access Optimisation shell.

Natural rail identifiers stay strings. Surrogate persistence ids are UUIDs and
timestamps are ISO-8601 UTC. Read schemas bind directly to ORM objects.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobState, Scenario
from app.domain.rail.nights import MAX_PHYSICAL_NIGHT, MIN_PHYSICAL_NIGHT
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


class SupplyDrop(BaseModel):
    """A location's nightly possession supply is cut mid-horizon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["supply_drop"] = "supply_drop"
    location_id: str
    new_supply: int = Field(ge=0)


class LocationUnavailable(BaseModel):
    """A location cannot be occupied, for some weeks or the whole horizon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["location_unavailable"] = "location_unavailable"
    location_id: str
    weeks: list[int] | None = Field(
        default=None,
        description="1-based weeks the location is closed; null means every week.",
    )


class NightUnavailable(BaseModel):
    """A physical night slot cannot host work, for some weeks or the horizon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["night_unavailable"] = "night_unavailable"
    physical_night: int = Field(ge=MIN_PHYSICAL_NIGHT, le=MAX_PHYSICAL_NIGHT)
    weeks: list[int] | None = Field(
        default=None,
        description="1-based weeks the night is closed; null means every week.",
    )


class UrgentActivityInjection(BaseModel):
    """A new urgent activity is injected into an already-solved schedule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["urgent_activity"] = "urgent_activity"
    activity_id: str
    contract_number: str
    activity_type: str | None = None
    start_location_id: str
    end_location_id: str
    total_accesses: int = Field(ge=1)
    planned_start_date: date
    predecessor_activity_id: str | None = None
    activity_priority: int = Field(default=1, ge=1, le=3)


Disruption = Annotated[
    SupplyDrop | LocationUnavailable | NightUnavailable | UrgentActivityInjection,
    Field(discriminator="kind"),
]


class ReplanRequest(BaseModel):
    """One mid-horizon disruption set to impact-assess and replan against."""

    model_config = ConfigDict(extra="forbid")

    disruptions: list[Disruption] = Field(min_length=1)
    time_limit_seconds: int | None = Field(default=None, gt=0)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    horizon_extension_weeks: int | None = Field(default=None, ge=0)


class ReplanRead(ReadModel):
    """The persisted impact assessment and minimal-churn replan diff."""

    id: uuid.UUID
    run_id: uuid.UUID
    job_id: uuid.UUID
    scenario: Scenario
    status: str
    safe: bool = False
    seed: int | None = None
    churn_cost: int = 0
    disruption: list[dict[str, Any]] = Field(default_factory=list)
    impact: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime


class SandboxRequest(BaseModel):
    """A controlled what-if evaluation over a completed scenario job.

    Only the listed inputs may vary. Any location, contract or scenario not
    present on the source run is rejected rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    scenario: Scenario | None = None
    supply: dict[str, int] = Field(default_factory=dict)
    workfronts: dict[str, int] = Field(default_factory=dict)
    horizon_extension_weeks: int | None = Field(default=None, ge=0)
    eclo_allowed: bool | None = None
    time_limit_seconds: int | None = Field(default=None, gt=0)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    fragility_location_id: str | None = None
    fragility_max_trials: int = Field(default=16, ge=2, le=64)


class SandboxMetricSet(BaseModel):
    """The objective facts reported for one what-if arm."""

    overrun_days_total: int
    excess_access_nights_total: int
    eclo_nights_total: int
    access_nights_total: int
    score: float


class SandboxOutcomeRead(BaseModel):
    """One what-if arm. Placements are present only when the arm is safe."""

    scenario: str
    feasible: bool
    safe: bool
    status: str
    metrics: SandboxMetricSet
    objective_breakdown: dict[str, Any] = Field(default_factory=dict)
    infeasibility_reasons: list[str] = Field(default_factory=list)
    witness: PhysicalWitnessReport | None = None
    access: list[dict[str, Any]] = Field(default_factory=list)
    occupancy: list[dict[str, Any]] = Field(default_factory=list)
    contract_results: list[dict[str, Any]] = Field(default_factory=list)


class SandboxFragility(BaseModel):
    """The bounded supply-fragility signal for one location."""

    location_id: str
    base_supply: int
    feasible_floor: int | None = None
    breaking_new_supply: int | None = None
    smallest_supply_reduction: int | None = None
    trials: int
    bounded: bool
    note: str


class SandboxRead(BaseModel):
    """A what-if evaluation and its optional fragility signal."""

    run_id: uuid.UUID
    job_id: uuid.UUID
    source_scenario: Scenario
    applied: dict[str, Any] = Field(default_factory=dict)
    baseline: SandboxMetricSet
    variant: SandboxOutcomeRead
    delta: dict[str, float] = Field(default_factory=dict)
    fragility: SandboxFragility | None = None


class ScheduleQueryRequest(BaseModel):
    """One typed, closed-grammar schedule query."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)


class ScheduleQueryCitation(BaseModel):
    """A pointer back to one persisted evidence source."""

    source: str
    fields: dict[str, Any] = Field(default_factory=dict)


class ScheduleQueryResponse(BaseModel):
    """A deterministic answer with the evidence and citations behind it."""

    run_id: uuid.UUID
    job_id: uuid.UUID
    scenario: Scenario
    query: str
    kind: str
    answerable: bool
    answer: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    citations: list[ScheduleQueryCitation] = Field(default_factory=list)


__all__ = [
    "ActivityExplanation",
    "ActivitySpanRead",
    "ContractResultRead",
    "Disruption",
    "LocationUnavailable",
    "NetworkResponse",
    "NightUnavailable",
    "ParseSummary",
    "PlanningRunRead",
    "ReplanRead",
    "ReplanRequest",
    "SandboxFragility",
    "SandboxMetricSet",
    "SandboxOutcomeRead",
    "SandboxRead",
    "SandboxRequest",
    "ScenarioJobCreate",
    "ScenarioJobRead",
    "ScheduleAccessRead",
    "ScheduleOccupancyRead",
    "ScheduleQueryCitation",
    "ScheduleQueryRequest",
    "ScheduleQueryResponse",
    "ScheduleResponse",
    "SupplyDrop",
    "UrgentActivityInjection",
    "ValidatorReportRead",
]
