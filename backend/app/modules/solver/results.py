"""Solver-boundary result contracts.

These are the only objects DEV-3/DEV-4 consume from the solver lane. They use
natural string keys, 1-based weeks and explicit booleans so they can be
serialised straight into the API and the ``trackaccess`` exporters without a
translation layer.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.rail.nights import MAX_PHYSICAL_NIGHT, MIN_PHYSICAL_NIGHT


class AccessPlacement(BaseModel):
    """One access occurrence for one activity.

    ``access_night`` stays the contract/type-local index published in
    ``SCHEDULE_ACCESS.csv``. ``physical_night`` is the global physical slot the
    solver assigned within the week (1..7). It is a solver fact for explanations
    and tests and is not part of the published CSV schema.
    """

    model_config = ConfigDict(frozen=True)

    activity_id: str
    access_seq: int = Field(ge=1)
    week: int = Field(ge=1)
    eclo: bool
    access_night: int = Field(ge=1)
    physical_night: int | None = Field(
        default=None, ge=MIN_PHYSICAL_NIGHT, le=MAX_PHYSICAL_NIGHT
    )


class OccupancyPlacement(BaseModel):
    """One location actually occupied by an activity in a week."""

    model_config = ConfigDict(frozen=True)

    activity_id: str
    week: int = Field(ge=1)
    location_id: str
    co_share_group: str


class ContractResult(BaseModel):
    """Completion summary for one contract."""

    model_config = ConfigDict(frozen=True)

    contract_number: str
    contract_priority: int
    planned_completion_date: date
    simulated_completion_date: date
    overrun_days: int
    last_week: int


class SolverResult(BaseModel):
    """The complete outcome of one scenario solve."""

    model_config = ConfigDict(frozen=True)

    feasible: bool
    scenario: str
    status: str
    horizon_weeks_used: int = Field(ge=0)
    access: tuple[AccessPlacement, ...] = ()
    occupancy: tuple[OccupancyPlacement, ...] = ()
    contract_results: tuple[ContractResult, ...] = ()
    contract_completion: dict[str, date] = Field(default_factory=dict)
    objective_breakdown: dict[str, Any] = Field(default_factory=dict)
    binding_reasons: dict[str, list[str]] = Field(default_factory=dict)
    infeasibility_reasons: tuple[str, ...] = ()

    @property
    def placements(self) -> tuple[AccessPlacement, ...]:
        """Alias matching the architecture blueprint's ``RailSolverResult``."""

        return self.access

    @property
    def workload_complete(self) -> bool:
        return self.feasible


def week_start(horizon_start: date, week: int) -> date:
    """Monday of a 1-based planning week."""

    return horizon_start + timedelta(days=(week - 1) * 7)


def week_end(horizon_start: date, week: int) -> date:
    """Sunday of a 1-based planning week."""

    return week_start(horizon_start, week) + timedelta(days=6)


__all__ = [
    "AccessPlacement",
    "ContractResult",
    "OccupancyPlacement",
    "SolverResult",
    "week_end",
    "week_start",
]
