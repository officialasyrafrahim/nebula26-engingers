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

from pydantic import BaseModel, ConfigDict

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
    return report_from_official_payload(payload)


def report_from_official_payload(payload: dict[str, Any]) -> ValidatorReport:
    """Normalise an official PS1 section 2.7 payload into a report."""

    scenario = str(payload.get("scenario", "A"))
    violations = tuple(
        HardViolation(
            rule=str(item.get("rule", "unknown")),
            severity="hard",
            detail=str(item.get("detail", "")),
        )
        for item in payload.get("hard_violations", ())
    )
    soft_payload = dict(payload.get("soft_scores") or {})
    soft_payload.setdefault("scenario", scenario)
    soft_payload.setdefault("formula_version", FORMULA_VERSION)
    soft_scores = SoftScores.model_validate(soft_payload)

    detail_payload = dict(payload.get("detail") or {})
    if "capacity_hotspots" in detail_payload:
        detail_payload["capacity_hotspots"] = tuple(detail_payload["capacity_hotspots"])
    detail = ValidatorDetail.model_validate(detail_payload)

    feasible = bool(payload.get("feasible", not violations))
    workload_complete = bool(
        payload.get("workload_complete", not any(v.rule == "workload" for v in violations))
    )
    return ValidatorReport(
        scenario=scenario,
        feasible=feasible,
        workload_complete=workload_complete,
        ready_for_submission=bool(
            payload.get("ready_for_submission", feasible and workload_complete)
        ),
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
