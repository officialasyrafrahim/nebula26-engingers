"""Scenario A/B/C policy semantics.

The compiled instance is scenario-independent; this module is the single place
where the hard/soft meaning of a rule is fixed per scenario. It is pure data,
so the solver can consume it without owning the policy. No solver is
implemented here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Scenario = Literal["A", "B", "C"]
CapacityMode = Literal["hard", "soft_unbounded", "soft_plus_one"]
EcloWindow = Literal["forbidden", "exempt", "two_week_per_line"]

SCENARIOS: tuple[str, ...] = ("A", "B", "C")

CONTRACT_PRIORITY_WEIGHTS: dict[int, int] = {1: 100, 2: 10, 3: 1}
ACTIVITY_PRIORITY_NUDGES: dict[int, float] = {1: 0.3, 2: 0.2, 3: 0.0}
EXCESS_ACCESS_NIGHT_COST = 7
ECLO_NIGHT_COST = 5


class ScenarioPolicy(BaseModel):
    """Hard/soft semantics and objective terms for one scenario."""

    model_config = ConfigDict(frozen=True)

    scenario: Scenario
    eclo_allowed: bool
    capacity_mode: CapacityMode
    capacity_soft_allowance: int
    planned_completion_hard: bool
    overrun_scored: bool
    excess_access_nights_scored: bool
    eclo_scored: bool
    eclo_window: EcloWindow

    @property
    def capacity_is_hard(self) -> bool:
        return self.capacity_mode == "hard"

    @property
    def planned_start_hard(self) -> bool:
        return True

    @property
    def predecessor_hard(self) -> bool:
        return True

    @property
    def closures_hard(self) -> bool:
        return True

    @property
    def mix_hard(self) -> bool:
        return True

    def hard_capacity_limit(self, supply_capacity: int) -> int | None:
        """Hard cap on possessions per location-week, or ``None`` if unbounded."""

        if self.capacity_mode == "hard":
            return supply_capacity
        if self.capacity_mode == "soft_plus_one":
            return supply_capacity + self.capacity_soft_allowance
        return None


_POLICIES: dict[str, ScenarioPolicy] = {
    "A": ScenarioPolicy(
        scenario="A",
        eclo_allowed=False,
        capacity_mode="hard",
        capacity_soft_allowance=0,
        planned_completion_hard=False,
        overrun_scored=True,
        excess_access_nights_scored=False,
        eclo_scored=False,
        eclo_window="forbidden",
    ),
    "B": ScenarioPolicy(
        scenario="B",
        eclo_allowed=True,
        capacity_mode="soft_unbounded",
        capacity_soft_allowance=0,
        planned_completion_hard=True,
        overrun_scored=False,
        excess_access_nights_scored=True,
        eclo_scored=True,
        eclo_window="exempt",
    ),
    "C": ScenarioPolicy(
        scenario="C",
        eclo_allowed=True,
        capacity_mode="soft_plus_one",
        capacity_soft_allowance=1,
        planned_completion_hard=False,
        overrun_scored=True,
        excess_access_nights_scored=True,
        eclo_scored=True,
        eclo_window="two_week_per_line",
    ),
}

SCENARIO_POLICIES = _POLICIES


def get_policy(scenario: str) -> ScenarioPolicy:
    """Return the frozen policy for ``A``, ``B`` or ``C``."""

    try:
        return _POLICIES[scenario]
    except KeyError:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}") from None


def contract_overrun_weight(contract_priority: int, activity_priority: int) -> float:
    """Banded overrun weight: contract tier dominates, activity priority nudges."""

    tier = CONTRACT_PRIORITY_WEIGHTS.get(contract_priority)
    nudge = ACTIVITY_PRIORITY_NUDGES.get(activity_priority)
    if tier is None or nudge is None:
        raise ValueError(
            f"unknown priority {contract_priority!r}/{activity_priority!r}; expected 1..3"
        )
    return tier * (1 + nudge)
