"""Objective construction for the rail CP-SAT model.

The published scores are penalties (lower is better). They are scaled by ten so
the activity-priority nudges (``+0.3``/``+0.2``/``+0.0``) stay integral inside
CP-SAT. The score multiplier exceeds the entire overshoot domain, so reducing
workload overshoot can never sacrifice even 0.1 of the published score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.rail.compiled import CompiledInstance
from app.modules.compiler.policy import (
    ECLO_NIGHT_COST,
    EXCESS_ACCESS_NIGHT_COST,
    ScenarioPolicy,
    contract_overrun_weight,
)
from app.modules.solver.variables import SolverVariables

OBJECTIVE_SCALE = 10
OVERSHOOT_WEIGHT = 1


@dataclass(slots=True)
class ObjectiveTerms:
    """Scaled coefficients plus the human-readable weights."""

    activity_weights: dict[str, float]
    scaled_activity_weights: dict[str, int]
    excess_weight: int
    eclo_weight: int
    overshoot_weight: int


def activity_weight(compiled: CompiledInstance, activity_id: str) -> float:
    """Banded overrun weight for one activity inside its contract tier."""

    compiled_activity = compiled.activities[activity_id]
    activity = compiled.instance.activities[activity_id]
    contract = compiled.instance.contracts[compiled_activity.contract_number]
    return contract_overrun_weight(
        contract.contract_priority, activity.activity_priority
    )


def build_objective(
    model: Any,
    compiled: CompiledInstance,
    variables: SolverVariables,
    policy: ScenarioPolicy,
) -> ObjectiveTerms:
    """Add the scaled penalty objective to ``model`` and return its terms."""

    activity_weights: dict[str, float] = {}
    scaled_activity_weights: dict[str, int] = {}
    terms: list[Any] = []

    for activity_id in variables.activity_order:
        weight = activity_weight(compiled, activity_id)
        scaled = round(weight * OBJECTIVE_SCALE)
        activity_weights[activity_id] = weight
        scaled_activity_weights[activity_id] = scaled
        if policy.overrun_scored and scaled:
            terms.append(scaled * variables.activity_overrun[activity_id])

    for variable in variables.excess.values():
        terms.append(EXCESS_ACCESS_NIGHT_COST * OBJECTIVE_SCALE * variable)

    for key, variable in variables.x.items():
        if key[3] == 1:
            terms.append(ECLO_NIGHT_COST * OBJECTIVE_SCALE * variable)

    overshoot_bound = sum(3 * len(weeks) for weeks in variables.activity_weeks.values())
    model.Minimize((overshoot_bound + 1) * sum(terms)
                   + OVERSHOOT_WEIGHT * variables.overshoot)

    return ObjectiveTerms(
        activity_weights=activity_weights,
        scaled_activity_weights=scaled_activity_weights,
        excess_weight=EXCESS_ACCESS_NIGHT_COST,
        eclo_weight=ECLO_NIGHT_COST,
        overshoot_weight=OVERSHOOT_WEIGHT,
    )


__all__ = [
    "OBJECTIVE_SCALE",
    "OVERSHOOT_WEIGHT",
    "ObjectiveTerms",
    "activity_weight",
    "build_objective",
]
