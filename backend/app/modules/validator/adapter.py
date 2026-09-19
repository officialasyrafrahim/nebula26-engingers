"""Official validator discovery and delegation.

The official validator is not shipped with the data pack. When a command is
configured (``RAIL_VALIDATOR_COMMAND`` or an explicit argument) and it runs
successfully, its JSON report is parsed and attributed to ``official``. When no
command is configured the adapter delegates to the fallback validator and
attributes the report to ``fallback``. It never relabels a fallback report as
official.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.compiler.policy import SCENARIOS
from app.modules.validator.fallback_validator import validate_directories
from app.modules.validator.report import (
    FORMULA_VERSION,
    Authority,
    HardViolation,
    SoftScores,
    ValidatorDetail,
    ValidatorReport,
)

DEFAULT_TIMEOUT_SECONDS = 300.0
VALIDATOR_COMMAND_ENV = "RAIL_VALIDATOR_COMMAND"


class OfficialValidatorError(RuntimeError):
    """Raised when a configured official validator cannot be invoked or parsed."""


class ValidationOutcome(BaseModel):
    """A report plus the provenance of the validator that produced it."""

    model_config = ConfigDict(frozen=True)

    report: ValidatorReport
    validator_source: Authority
    official_available: bool
    official_command: str | None = None


def resolve_validator_command(command: str | None = None) -> str | None:
    """Return the configured official validator command, if any."""

    if command:
        return command
    env = os.environ.get(VALIDATOR_COMMAND_ENV)
    return env or None


def validate_with_adapter(
    instance_dir: str | os.PathLike[str],
    submission_dir: str | os.PathLike[str],
    scenario: str | None = None,
    *,
    command: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ValidationOutcome:
    """Validate via the official validator when configured, else the fallback."""

    resolved = resolve_validator_command(command)
    if resolved is None:
        report = validate_directories(
            instance_dir, submission_dir, scenario, authority="fallback"
        )
        return ValidationOutcome(
            report=report.with_source("fallback"),
            validator_source="fallback",
            official_available=False,
            official_command=None,
        )

    report = run_official_validator(
        resolved, instance_dir, submission_dir, scenario, timeout_seconds=timeout_seconds
    )
    return ValidationOutcome(
        report=report,
        validator_source="official",
        official_available=True,
        official_command=resolved,
    )


def run_official_validator(
    command: str,
    instance_dir: str | os.PathLike[str],
    submission_dir: str | os.PathLike[str],
    scenario: str | None = None,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ValidatorReport:
    """Invoke a configured validator command and parse its JSON report."""

    argv = shlex.split(command)
    if not argv:
        raise OfficialValidatorError("validator command is empty")

    args = [*argv, str(Path(instance_dir)), str(Path(submission_dir))]
    if scenario:
        args.append(scenario)
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OfficialValidatorError(f"could not run validator {command!r}: {exc}") from exc

    if completed.returncode != 0:
        raise OfficialValidatorError(
            f"validator {command!r} exited {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OfficialValidatorError(
            f"validator {command!r} did not return JSON: {exc}"
        ) from exc
    return report_from_official_payload(payload, requested_scenario=scenario)


_TRUE_STRINGS = frozenset({"1", "true", "yes", "y", "on"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "n", "off"})


def _as_bool(value: Any, *, default: bool) -> bool:
    """Coerce a JSON value to bool, falling back to ``default`` when ambiguous."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return default


def _parse_official_violations(payload: dict[str, Any]) -> tuple[HardViolation, ...]:
    """Parse ``hard_violations``, rejecting any non-array or non-object item."""

    raw = payload.get("hard_violations", ())
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise OfficialValidatorError("hard_violations must be a JSON array")
    violations: list[HardViolation] = []
    for item in raw:
        if not isinstance(item, dict):
            raise OfficialValidatorError("each hard_violation must be a JSON object")
        violations.append(
            HardViolation(
                rule=str(item.get("rule", "unknown")),
                severity="hard",
                detail=str(item.get("detail", "")),
            )
        )
    return tuple(violations)


def report_from_official_payload(
    payload: Any, *, requested_scenario: str | None = None
) -> ValidatorReport:
    """Normalise an official PS1 section 2.7 payload into a trusted report.

    The official program is an external process, so its report is treated as
    untrusted input. A malformed payload, an unknown or mismatched scenario, an
    infeasible status, a workload violation or any hard violation can never
    yield ``ready_for_submission``. Readiness is always the conjunction of the
    parsed facts rather than a flag the payload can assert on its own.
    """

    if not isinstance(payload, dict):
        raise OfficialValidatorError("official validator payload is not a JSON object")

    scenario = str(payload.get("scenario", "A"))
    if scenario not in SCENARIOS:
        raise OfficialValidatorError(
            f"official validator reported unknown scenario {scenario!r}"
        )
    if requested_scenario is not None and scenario != requested_scenario:
        raise OfficialValidatorError(
            f"official validator reported scenario {scenario!r} but "
            f"{requested_scenario!r} was requested"
        )

    violations = _parse_official_violations(payload)
    status = str(payload.get("status", "")).strip().upper()
    has_workload_violation = any(v.rule == "workload" for v in violations)
    has_hard_violation = bool(violations)

    feasible = (
        _as_bool(payload.get("feasible"), default=not has_hard_violation)
        and not has_hard_violation
        and status != "INFEASIBLE"
    )
    workload_complete = (
        _as_bool(payload.get("workload_complete"), default=not has_workload_violation)
        and not has_workload_violation
    )
    ready_for_submission = (
        _as_bool(
            payload.get("ready_for_submission"),
            default=feasible and workload_complete,
        )
        and feasible
        and workload_complete
    )

    raw_soft = payload.get("soft_scores")
    if raw_soft is None:
        soft_payload: dict[str, Any] = {}
    elif isinstance(raw_soft, dict):
        soft_payload = dict(raw_soft)
    else:
        raise OfficialValidatorError("soft_scores must be a JSON object")
    soft_payload.setdefault("scenario", scenario)
    soft_payload.setdefault("formula_version", FORMULA_VERSION)
    try:
        soft_scores = SoftScores.model_validate(soft_payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise OfficialValidatorError(
            f"invalid soft_scores in official report: {exc}"
        ) from exc

    raw_detail = payload.get("detail")
    if raw_detail is None:
        detail_payload: dict[str, Any] = {}
    elif isinstance(raw_detail, dict):
        detail_payload = dict(raw_detail)
    else:
        raise OfficialValidatorError("detail must be a JSON object")
    try:
        if "capacity_hotspots" in detail_payload:
            hotspots = detail_payload["capacity_hotspots"] or ()
            detail_payload["capacity_hotspots"] = tuple(hotspots)
        detail = ValidatorDetail.model_validate(detail_payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise OfficialValidatorError(
            f"invalid detail in official report: {exc}"
        ) from exc

    return ValidatorReport(
        scenario=scenario,
        feasible=feasible,
        workload_complete=workload_complete,
        ready_for_submission=ready_for_submission,
        authority="official",
        validator_source="official",
        hard_violations=violations,
        soft_scores=soft_scores,
        detail=detail,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "VALIDATOR_COMMAND_ENV",
    "OfficialValidatorError",
    "ValidationOutcome",
    "report_from_official_payload",
    "resolve_validator_command",
    "run_official_validator",
    "validate_with_adapter",
]
