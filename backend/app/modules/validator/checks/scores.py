"""Soft-score computation for the PS1 section 2.7 report."""

from __future__ import annotations

from datetime import timedelta

from app.modules.compiler.policy import (
    ECLO_NIGHT_COST,
    EXCESS_ACCESS_NIGHT_COST,
    contract_overrun_weight,
)
from app.modules.validator.checks.context import ValidationContext
from app.modules.validator.report import FORMULA_VERSION, SoftScores, ValidatorDetail


def compute_soft_scores(ctx: ValidationContext, *, feasible: bool) -> SoftScores:
    priority_overrun: dict[str, int] = {"1": 0, "2": 0, "3": 0}
    overrun_total = 0
    earliness_total = 0
    overrunning = 0
    weighted = 0.0

    for row in ctx.result_rows:
        contract = ctx.instance.contracts.get(row.contract_number)
        if contract is None:
            continue
        overrun_total += row.overrun_days
        if row.overrun_days > 0:
            overrunning += 1
        priority_overrun[str(contract.contract_priority)] = (
            priority_overrun.get(str(contract.contract_priority), 0) + row.overrun_days
        )
        earliness_total += max(
            0, (contract.planned_completion_date - row.simulated_completion_date).days
        )

    for activity_id, rows in ctx.access_by_activity.items():
        activity = ctx.instance.activities.get(activity_id)
        if activity is None or not rows:
            continue
        contract = ctx.instance.contracts[activity.contract_number]
        completion = ctx.instance.horizon_start + timedelta(
            days=(max(row.week for row in rows) - 1) * 7 + 6
        )
        activity_overrun = max(
            0, (completion - contract.planned_completion_date).days
        )
        weighted += contract_overrun_weight(
            contract.contract_priority, activity.activity_priority
        ) * activity_overrun

    eclo_nights = sum(1 for row in _all_access(ctx) if row.eclo)
    excess = ctx.excess_access_nights_total
    objective: float | None = None
    formula: str | None = None
    if feasible:
        if ctx.scenario == "B":
            objective = EXCESS_ACCESS_NIGHT_COST * excess + ECLO_NIGHT_COST * eclo_nights
        elif ctx.scenario == "C":
            objective = (
                weighted
                + EXCESS_ACCESS_NIGHT_COST * excess
                + ECLO_NIGHT_COST * eclo_nights
            )
        else:
            objective = weighted
        formula = FORMULA_VERSION

    return SoftScores(
        scenario=ctx.scenario,
        overrun_days_total=overrun_total,
        contracts_overrunning=overrunning,
        earliness_days_total=earliness_total,
        excess_access_nights_total=excess,
        eclo_nights_total=eclo_nights,
        priority_overrun=priority_overrun,
        priority_weighted_score=round(weighted, 6),
        objective_score=objective,
        formula_version=formula,
    )


def compute_detail(ctx: ValidationContext) -> ValidatorDetail:
    access = _all_access(ctx)
    return ValidatorDetail(
        capacity_hotspots=tuple(ctx.capacity_hotspots),
        nights_scheduled=len(access),
        eclo_nights=sum(1 for row in access if row.eclo),
    )


def _all_access(ctx: ValidationContext):
    return [row for rows in ctx.access_by_activity.values() for row in rows]


__all__ = ["compute_detail", "compute_soft_scores"]
