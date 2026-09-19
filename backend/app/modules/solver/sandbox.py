"""Deterministic fragility and what-if sandbox (F-BONUS-002).

The sandbox answers two questions about an already-solved job without touching
its published CSVs:

* *what if* one or more controlled inputs changed? It re-solves the source
  instance under the requested supply, workfront, horizon or ECLO variation and
  reports the resulting objective facts plus whether the schedule stayed
  feasible.
* *how fragile* is the schedule to a supply cut? It finds the smallest supply
  reduction that breaks feasibility with a bounded binary search.

Safety semantics are inherited unchanged. The sandbox reuses the compiled
instance, the scenario policies and the engine's own solve path, so hard
constraints keep their exact meaning. Every feasible variant is re-checked by
the independent physical witness; a witness failure is reported as ``UNSAFE``
and the schedule is withheld, never returned.

.. warning::

   ``engine.py`` is intentionally not modified. The private engine entry point
   :func:`app.modules.solver.engine._solve` is imported so a derived scenario
   policy (for example an ECLO allowance toggle) sees exactly the same safety
   construction as the source solve. If that private helper changes, this module
   must be re-checked.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.domain.rail.compiled import CompiledInstance
from app.modules.compiler.policy import get_policy
from app.modules.solver import engine as _engine
from app.modules.solver.model import (
    DEFAULT_HORIZON_EXTENSION_WEEKS,
    DEFAULT_SEED,
    DEFAULT_TIME_LIMIT_SECONDS,
)
from app.modules.solver.results import SolverResult
from app.modules.validator.witness import PhysicalWitnessReport, check_physical_witness

SCENARIOS = ("A", "B", "C")
MAX_FRAGILITY_TRIALS = 24


class SandboxError(ValueError):
    """Base class for a rejected sandbox request."""


class UnknownEntityError(SandboxError):
    """A knob names a location, contract or scenario the run does not contain."""


class InvalidKnobError(SandboxError):
    """A knob value is outside the allowed range."""


class FragilitySearchLimit(SandboxError):
    """The bounded fragility search could not finish within its trial budget."""


@dataclass(frozen=True)
class WhatIfKnobs:
    """The small, controlled set of inputs a what-if evaluation may vary."""

    scenario: str | None = None
    supply: Mapping[str, int] = field(default_factory=dict)
    workfronts: Mapping[str, int] = field(default_factory=dict)
    horizon_extension_weeks: int | None = None
    eclo_allowed: bool | None = None


@dataclass(frozen=True)
class SandboxOutcome:
    """One what-if outcome, safe or honestly infeasible."""

    scenario: str
    feasible: bool
    safe: bool
    status: str
    result: SolverResult
    witness: PhysicalWitnessReport | None
    applied: dict[str, Any]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class FragilitySignal:
    """How close a schedule is to losing feasibility under a supply cut."""

    location_id: str
    base_supply: int
    feasible_floor: int | None
    breaking_new_supply: int | None
    smallest_supply_reduction: int | None
    trials: int
    bounded: bool
    note: str


def resolve_scenario(scenario: str, knobs: WhatIfKnobs) -> str:
    """Return the effective scenario, rejecting anything outside A/B/C."""

    effective = knobs.scenario or scenario
    if effective not in SCENARIOS:
        raise UnknownEntityError(
            f"unknown scenario {effective!r}; expected one of {SCENARIOS}"
        )
    return effective


def _resolve_policy(scenario: str, knobs: WhatIfKnobs):
    policy = get_policy(scenario)
    if knobs.eclo_allowed is not None:
        policy = policy.model_copy(update={"eclo_allowed": bool(knobs.eclo_allowed)})
    return policy


def _resolve_instance(
    compiled: CompiledInstance, knobs: WhatIfKnobs
) -> tuple[CompiledInstance, dict[str, Any]]:
    """Apply the controlled knobs to a copy of the compiled instance."""

    updates: dict[str, Any] = {}
    applied: dict[str, Any] = {}

    if knobs.supply:
        capacities = dict(compiled.location_capacities)
        for location_id, value in sorted(knobs.supply.items()):
            if location_id not in capacities:
                raise UnknownEntityError(
                    f"supply override names unknown location {location_id!r}"
                )
            if value < 0:
                raise InvalidKnobError(
                    f"supply for {location_id!r} must be >= 0, got {value}"
                )
            capacities[location_id] = int(value)
        updates["location_capacities"] = capacities
        applied["supply"] = {key: int(value) for key, value in sorted(knobs.supply.items())}

    if knobs.workfronts:
        workfronts = dict(compiled.contract_workfronts)
        for contract_number, value in sorted(knobs.workfronts.items()):
            if contract_number not in workfronts:
                raise UnknownEntityError(
                    f"workfront override names unknown contract {contract_number!r}"
                )
            if value < 1:
                raise InvalidKnobError(
                    f"workfront for {contract_number!r} must be >= 1, got {value}"
                )
            workfronts[contract_number] = int(value)
        updates["contract_workfronts"] = workfronts
        applied["workfronts"] = {
            key: int(value) for key, value in sorted(knobs.workfronts.items())
        }

    variant = compiled.model_copy(update=updates) if updates else compiled
    return variant, applied


def evaluate_what_if(
    compiled: CompiledInstance,
    scenario: str,
    knobs: WhatIfKnobs | None = None,
    *,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    seed: int = DEFAULT_SEED,
    horizon_extension_weeks: int = DEFAULT_HORIZON_EXTENSION_WEEKS,
) -> SandboxOutcome:
    """Re-solve one controlled variant and report its objective and safety.

    A feasible variant is returned only when the independent physical witness
    accepts it. A witness rejection is reported as ``UNSAFE`` with the schedule
    withheld; an infeasible variant carries the engine's status and reasons.
    """

    knobs = knobs or WhatIfKnobs()
    effective = resolve_scenario(scenario, knobs)
    policy = _resolve_policy(effective, knobs)
    variant, applied = _resolve_instance(compiled, knobs)

    extension = (
        knobs.horizon_extension_weeks
        if knobs.horizon_extension_weeks is not None
        else horizon_extension_weeks
    )
    if knobs.horizon_extension_weeks is not None:
        applied["horizon_extension_weeks"] = int(extension)
    if knobs.eclo_allowed is not None:
        applied["eclo_allowed"] = bool(knobs.eclo_allowed)
    applied["scenario"] = effective

    result = _engine._solve(
        variant,
        policy,
        float(time_limit_seconds),
        int(seed),
        int(extension),
    )

    if not result.feasible:
        return SandboxOutcome(
            scenario=effective,
            feasible=False,
            safe=False,
            status=result.status,
            result=result,
            witness=None,
            applied=applied,
            notes=(),
        )

    witness = check_physical_witness(
        variant, policy, result.access, result.occupancy
    )
    if not witness.passed:
        withheld = result.model_copy(
            update={
                "feasible": False,
                "status": "UNSAFE",
                "access": (),
                "occupancy": (),
                "contract_results": (),
                "contract_completion": {},
            }
        )
        return SandboxOutcome(
            scenario=effective,
            feasible=False,
            safe=False,
            status="UNSAFE",
            result=withheld,
            witness=witness,
            applied=applied,
            notes=("physical witness rejected the variant; schedule withheld",),
        )

    return SandboxOutcome(
        scenario=effective,
        feasible=True,
        safe=True,
        status=result.status,
        result=result,
        witness=witness,
        applied=applied,
        notes=(),
    )


def fragility_supply(
    compiled: CompiledInstance,
    scenario: str,
    location_id: str,
    *,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    seed: int = DEFAULT_SEED,
    horizon_extension_weeks: int = DEFAULT_HORIZON_EXTENSION_WEEKS,
    max_trials: int = 16,
) -> FragilitySignal:
    """Find the smallest supply reduction that breaks feasibility.

    Feasibility is monotone in a location's supply for every scenario with a
    hard capacity limit: a smaller supply can only shrink the feasible set, so
    the boundary is found with a bounded binary search. Scenario B treats
    capacity as soft, so a supply cut can never break feasibility and the signal
    says so explicitly. Each trial is a fixed-seed solve, so the result is
    deterministic.
    """

    if location_id not in compiled.location_capacities:
        raise UnknownEntityError(
            f"fragility check names unknown location {location_id!r}"
        )
    if max_trials < 2:
        raise InvalidKnobError("fragility max_trials must be at least 2")
    base = int(compiled.location_capacities[location_id])
    policy = get_policy(scenario)
    if policy.capacity_mode == "soft_unbounded":
        return FragilitySignal(
            location_id=location_id,
            base_supply=base,
            feasible_floor=None,
            breaking_new_supply=None,
            smallest_supply_reduction=None,
            trials=0,
            bounded=True,
            note=(
                f"scenario {scenario} treats capacity as soft; a supply reduction "
                "cannot break feasibility"
            ),
        )

    trials = 0

    def feasible_at(supply: int) -> bool:
        nonlocal trials
        if trials >= max_trials:
            raise FragilitySearchLimit(
                f"fragility search exceeded the {max_trials}-trial bound"
            )
        trials += 1
        outcome = evaluate_what_if(
            compiled,
            scenario,
            WhatIfKnobs(supply={location_id: supply}),
            time_limit_seconds=time_limit_seconds,
            seed=seed,
            horizon_extension_weeks=horizon_extension_weeks,
        )
        return outcome.feasible and outcome.safe

    if not feasible_at(base):
        raise InvalidKnobError(
            f"the source schedule is not feasible at supply {base} for "
            f"location {location_id!r}"
        )
    if base == 0:
        return FragilitySignal(
            location_id=location_id,
            base_supply=0,
            feasible_floor=0,
            breaking_new_supply=None,
            smallest_supply_reduction=None,
            trials=trials,
            bounded=True,
            note="the location already has zero supply",
        )
    if feasible_at(0):
        return FragilitySignal(
            location_id=location_id,
            base_supply=base,
            feasible_floor=0,
            breaking_new_supply=None,
            smallest_supply_reduction=None,
            trials=trials,
            bounded=True,
            note=(
                "the schedule stays feasible even at supply 0; no reduction "
                "within the search breaks it"
            ),
        )

    low, high = 0, base
    while high - low > 1:
        middle = (low + high) // 2
        if feasible_at(middle):
            high = middle
        else:
            low = middle
    feasible_floor = high
    breaking_new_supply = feasible_floor - 1
    smallest_supply_reduction = base - breaking_new_supply
    note = (
        f"supply {base} is feasible; {location_id!r} breaks at supply "
        f"{breaking_new_supply}, so the smallest breaking reduction is "
        f"{smallest_supply_reduction}"
    )
    return FragilitySignal(
        location_id=location_id,
        base_supply=base,
        feasible_floor=feasible_floor,
        breaking_new_supply=breaking_new_supply,
        smallest_supply_reduction=smallest_supply_reduction,
        trials=trials,
        bounded=True,
        note=note,
    )


def metrics_from_result(result: SolverResult) -> dict[str, float]:
    """Objective facts for one solve outcome, from its persisted breakdown."""

    breakdown = result.objective_breakdown or {}
    return {
        "overrun_days_total": int(breakdown.get("overrun_days_total", 0) or 0),
        "excess_access_nights_total": int(
            breakdown.get("excess_access_nights_total", 0) or 0
        ),
        "eclo_nights_total": int(breakdown.get("eclo_nights_total", 0) or 0),
        "access_nights_total": int(
            breakdown.get("access_nights_total", len(result.access)) or 0
        ),
        "score": float(breakdown.get("score", 0.0) or 0.0),
    }


__all__ = [
    "FragilitySearchLimit",
    "FragilitySignal",
    "InvalidKnobError",
    "MAX_FRAGILITY_TRIALS",
    "SCENARIOS",
    "SandboxError",
    "SandboxOutcome",
    "UnknownEntityError",
    "WhatIfKnobs",
    "evaluate_what_if",
    "fragility_supply",
    "metrics_from_result",
    "resolve_scenario",
]
