"""Fallback reference-equivalent validator.

This validator is independent of CP-SAT: it consumes only the canonical
:class:`PlanningInstance` (re-derived from the eight instance CSVs) and a parsed
:class:`SubmissionBundle` (re-derived from the three submission CSVs). It never
reads a ``SolverResult`` or any solver variable, so a plan cannot pass by
construction: the rules are re-evaluated from the published tables.

The report shape is identical to the official validator's (PS1 section 2.7),
with ``authority``/``validator_source`` set to ``fallback``. The adapter in
:mod:`app.modules.validator.adapter` is the only place allowed to label a report
``official``.
"""

from __future__ import annotations

import os

from app.domain.rail.errors import RailDataError
from app.domain.rail.instance_model import PlanningInstance
from app.modules.compiler.policy import SCENARIOS, get_policy
from app.modules.compiler.rule_compiler import compile_instance
from app.modules.export.bundle import SubmissionBundle, load_bundle
from app.modules.export.schemas import SubmissionParseError
from app.modules.instance.service import load_instance
from app.modules.validator.checks import ValidationContext, run_checks
from app.modules.validator.checks.scores import compute_detail, compute_soft_scores
from app.modules.validator.report import (
    Authority,
    HardViolation,
    ValidatorReport,
    empty_report,
)


def infer_scenario(bundle: SubmissionBundle) -> str | None:
    """Return the single scenario declared by ``RESULTS.csv``, else ``None``."""

    scenarios = {row.scenario for row in bundle.results}
    if len(scenarios) == 1:
        return next(iter(scenarios))
    return None


def validate_bundle(
    instance: PlanningInstance,
    bundle: SubmissionBundle,
    scenario: str | None = None,
    *,
    authority: Authority = "fallback",
) -> ValidatorReport:
    """Validate one parsed submission against a canonical instance."""

    resolved = scenario or infer_scenario(bundle) or "A"
    policy = get_policy(resolved) if resolved in SCENARIOS else get_policy("A")
    compiled = compile_instance(instance)

    ctx = ValidationContext(
        compiled=compiled,
        policy=policy,
        scenario=resolved,
        authority=authority,
        result_rows=bundle.results,
    )
    ctx.index(bundle.access, bundle.occupancy)
    run_checks(ctx)

    feasible = not ctx.violations
    workload_complete = not ctx.has_rule("workload")
    return ValidatorReport(
        scenario=resolved,
        feasible=feasible,
        workload_complete=workload_complete,
        ready_for_submission=feasible and workload_complete,
        authority=authority,
        validator_source=authority,
        hard_violations=tuple(ctx.violations),
        soft_scores=compute_soft_scores(ctx, feasible=feasible),
        detail=compute_detail(ctx),
    )


def validate_directories(
    instance_dir: str | os.PathLike[str],
    submission_dir: str | os.PathLike[str],
    scenario: str | None = None,
    *,
    authority: Authority = "fallback",
) -> ValidatorReport:
    """Load an instance and submission from disk and validate them."""

    try:
        instance = load_instance(instance_dir)
    except RailDataError as exc:
        return empty_report(
            scenario or "A",
            authority=authority,
            violations=(
                HardViolation(rule="schema", detail=f"invalid instance: {exc}"),
            ),
            parse_errors=tuple(str(issue) for issue in exc.issues),
        )

    try:
        bundle = load_bundle(submission_dir)
    except SubmissionParseError as exc:
        return empty_report(
            scenario or "A",
            authority=authority,
            violations=(
                HardViolation(rule="schema", detail=f"invalid submission: {exc}"),
            ),
            parse_errors=tuple(str(issue) for issue in exc.issues),
        )

    return validate_bundle(instance, bundle, scenario, authority=authority)


def validate_compiled(
    compiled,
    bundle: SubmissionBundle,
    scenario: str | None = None,
    *,
    authority: Authority = "fallback",
) -> ValidatorReport:
    """Validate a bundle against an already-compiled instance (no CP-SAT)."""

    return validate_bundle(
        compiled.instance, bundle, scenario, authority=authority
    )


__all__ = [
    "infer_scenario",
    "validate_bundle",
    "validate_compiled",
    "validate_directories",
]
