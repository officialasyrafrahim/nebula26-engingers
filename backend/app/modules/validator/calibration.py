"""Official-validator calibration hooks (F-VALIDATOR-004 scaffolding).

The official validator is not shipped with the data pack. Calibration compares
the fallback report against the official program when a command is configured,
and is explicitly **blocked** otherwise. A blocked calibration never claims an
official result and never relabels fallback output as official.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.validator.adapter import (
    OfficialValidatorError,
    resolve_validator_command,
    run_official_validator,
)
from app.modules.validator.fallback_validator import validate_directories
from app.modules.validator.report import Authority, ValidatorReport

CalibrationStatus = Literal["match", "diverged", "blocked"]
SCORE_TOLERANCE = 1e-6


class CalibrationResult(BaseModel):
    """The outcome of comparing fallback and official validation."""

    model_config = ConfigDict(frozen=True)

    status: CalibrationStatus
    official_available: bool
    official_command: str | None = None
    fallback: ValidatorReport | None = None
    official: ValidatorReport | None = None
    divergences: tuple[str, ...] = ()
    note: str = ""

    @property
    def official_authority(self) -> Authority | None:
        return self.official.authority if self.official is not None else None


def compare_reports(
    fallback: ValidatorReport, official: ValidatorReport
) -> tuple[str, ...]:
    """Return human-readable divergences between two reports (empty = match)."""

    divergences: list[str] = []
    if fallback.scenario != official.scenario:
        divergences.append(
            f"scenario differs: fallback={fallback.scenario!r} official={official.scenario!r}"
        )
    if fallback.feasible != official.feasible:
        divergences.append(
            f"feasible differs: fallback={fallback.feasible} official={official.feasible}"
        )
    fallback_rules = sorted(fallback.rules)
    official_rules = sorted(official.rules)
    if fallback_rules != official_rules:
        divergences.append(
            f"rule tags differ: fallback={fallback_rules} official={official_rules}"
        )
    fallback_score = fallback.soft_scores.objective_score
    official_score = official.soft_scores.objective_score
    if (fallback_score is None) != (official_score is None):
        divergences.append(
            "objective presence differs: "
            f"fallback={fallback_score!r} official={official_score!r}"
        )
    elif (
        fallback_score is not None
        and official_score is not None
        and abs(fallback_score - official_score) > SCORE_TOLERANCE
    ):
        divergences.append(
            f"objective score differs: fallback={fallback_score} official={official_score}"
        )
    return tuple(divergences)


def run_calibration(
    instance_dir: str | os.PathLike[str],
    submission_dir: str | os.PathLike[str],
    scenario: str | None = None,
    *,
    command: str | None = None,
    timeout_seconds: float = 300.0,
) -> CalibrationResult:
    """Calibrate fallback against the official validator, or report blocked.

    When no command is supplied (argument or ``RAIL_VALIDATOR_COMMAND``), the
    result is ``blocked`` and neither report is labelled official.
    """

    fallback = validate_directories(
        instance_dir, submission_dir, scenario, authority="fallback"
    )
    resolved = resolve_validator_command(command)
    if resolved is None:
        return CalibrationResult(
            status="blocked",
            official_available=False,
            official_command=None,
            fallback=fallback,
            note=(
                "official validator not supplied; set RAIL_VALIDATOR_COMMAND to "
                "calibrate fallback semantics (fallback shown for reference only)"
            ),
        )

    try:
        official = run_official_validator(
            resolved,
            instance_dir,
            submission_dir,
            scenario,
            timeout_seconds=timeout_seconds,
        )
    except OfficialValidatorError as exc:
        return CalibrationResult(
            status="diverged",
            official_available=True,
            official_command=resolved,
            fallback=fallback,
            official=None,
            divergences=(f"official validator error: {exc}",),
            note="official validator failed to run or parse",
        )

    divergences = compare_reports(fallback, official)
    return CalibrationResult(
        status="match" if not divergences else "diverged",
        official_available=True,
        official_command=resolved,
        fallback=fallback,
        official=official,
        divergences=divergences,
        note="fallback and official reports agree"
        if not divergences
        else "fallback and official reports disagree",
    )


__all__ = [
    "CalibrationResult",
    "CalibrationStatus",
    "compare_reports",
    "run_calibration",
]
