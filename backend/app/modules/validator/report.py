"""Validator report contract matching PS1 section 2.7.

The report is the machine-readable proof that a submission was checked. It is
identical in shape whether the authority is the official validator or the
bundled fallback; the only difference is the ``authority``/``validator_source``
fields, which must never claim the fallback is the official program.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["hard"]
Authority = Literal["official", "fallback"]

FORMULA_VERSION = "ps1-2.5"


class HardViolation(BaseModel):
    """One hard-rule breach with its rule tag and human-readable pinpoint."""

    model_config = ConfigDict(frozen=True)

    rule: str
    severity: Severity = "hard"
    detail: str


class SoftScores(BaseModel):
    """Quality metrics behind the Scenario A/B/C objectives (lower is better)."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    overrun_days_total: int = 0
    contracts_overrunning: int = 0
    earliness_days_total: int = 0
    excess_access_nights_total: int = 0
    eclo_nights_total: int = 0
    priority_overrun: dict[str, int] = Field(
        default_factory=lambda: {"1": 0, "2": 0, "3": 0}
    )
    priority_weighted_score: float = 0.0
    objective_score: float | None = None
    formula_version: str | None = None


class ValidatorDetail(BaseModel):
    """Supplementary diagnostics surfaced next to the scores."""

    model_config = ConfigDict(frozen=True)

    capacity_hotspots: tuple[dict[str, Any], ...] = ()
    nights_scheduled: int = 0
    eclo_nights: int = 0


class ValidatorReport(BaseModel):
    """The complete PS1 section 2.7 validation report."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    feasible: bool
    workload_complete: bool
    ready_for_submission: bool
    authority: Authority = "fallback"
    validator_source: Authority = "fallback"
    hard_violations: tuple[HardViolation, ...] = ()
    soft_scores: SoftScores
    detail: ValidatorDetail
    parse_errors: tuple[str, ...] = ()

    @property
    def rules(self) -> tuple[str, ...]:
        """Return the ordered, unique rule tags that fired."""

        seen: list[str] = []
        for violation in self.hard_violations:
            if violation.rule not in seen:
                seen.append(violation.rule)
        return tuple(seen)

    def with_source(self, source: Authority) -> ValidatorReport:
        """Return a copy attributed to ``source`` (never lies about authority)."""

        return self.model_copy(update={"authority": source, "validator_source": source})


def empty_report(
    scenario: str,
    *,
    authority: Authority = "fallback",
    violations: tuple[HardViolation, ...] = (),
    parse_errors: tuple[str, ...] = (),
) -> ValidatorReport:
    """Build a report with zeroed soft scores, used when parsing fails."""

    return ValidatorReport(
        scenario=scenario,
        feasible=not violations,
        workload_complete=False,
        ready_for_submission=False,
        authority=authority,
        validator_source=authority,
        hard_violations=violations,
        soft_scores=SoftScores(scenario=scenario),
        detail=ValidatorDetail(),
        parse_errors=parse_errors,
    )


__all__ = [
    "FORMULA_VERSION",
    "Authority",
    "HardViolation",
    "Severity",
    "SoftScores",
    "ValidatorDetail",
    "ValidatorReport",
    "empty_report",
]
