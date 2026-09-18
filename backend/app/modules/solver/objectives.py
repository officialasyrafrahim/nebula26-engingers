"""Objective construction for the rail CP-SAT model.

The published scores are penalties (lower is better). They are scaled by ten so
the activity-priority nudges (``+0.3``/``+0.2``/``+0.0``) stay integral inside
CP-SAT, and a negligible unit-cost overshoot term removes gratuitous extra
accesses without disturbing the scored terms.
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

    contract_weights: dict[str, float]
    scaled_contract_weights: dict[str, int]
    excess_weight: int
    eclo_weight: int
    overshoot_weight: int


def contract_weight(compiled: CompiledInstance, contract_number: str) -> float:
    """Banded overrun weight, using the contract's highest-priority activity."""

    activities = compiled.activities_for_contract(contract_number)
    if not activities:
        return 0.0
    contract = compiled.instance.contracts[contract_number]
    nudge = min(
        compiled.instance.activities[activity.activity_id].activity_priority
        for activity in activities
    )
    return contract_overrun_weight(contract.contract_priority, nudge)


def build_objective(
    model: Any,
    compiled: CompiledInstance,
    variables: SolverVariables,
    policy: ScenarioPolicy,
) -> ObjectiveTerms:
    """Add the scaled penalty objective to ``model`` and return its terms."""

    contract_weights: dict[str, float] = {}
    scaled_contract_weights: dict[str, int] = {}
    terms: list[Any] = []

    for contract_number in sorted(variables.overrun):
        weight = contract_weight(compiled, contract_number)
        scaled = round(weight * OBJECTIVE_SCALE)
        contract_weights[contract_number] = weight
        scaled_contract_weights[contract_number] = scaled
        if policy.overrun_scored and scaled:
            terms.append(scaled * variables.overrun[contract_number])

    for variable in variables.excess.values():
        terms.append(EXCESS_ACCESS_NIGHT_COST * OBJECTIVE_SCALE * variable)

    for key, variable in variables.x.items():
        if key[3] == 1:
            terms.append(ECLO_NIGHT_COST * OBJECTIVE_SCALE * variable)

    terms.append(OVERSHOOT_WEIGHT * variables.overshoot)
    model.Minimize(sum(terms))

    return ObjectiveTerms(
        contract_weights=contract_weights,
        scaled_contract_weights=scaled_contract_weights,
        excess_weight=EXCESS_ACCESS_NIGHT_COST,
        eclo_weight=ECLO_NIGHT_COST,
        overshoot_weight=OVERSHOOT_WEIGHT,
    )


__all__ = [
    "OBJECTIVE_SCALE",
    "OVERSHOOT_WEIGHT",
    "ObjectiveTerms",
    "build_objective",
    "contract_weight",
]
