"""Independent hard-rule checks for the fallback validator."""

from __future__ import annotations

from app.modules.validator.checks import (
    allocation,
    capacity,
    closures,
    dates,
    mix,
    occupancy,
    scenario,
    workload,
)
from app.modules.validator.checks.context import ValidationContext

CHECK_ORDER = (
    workload,
    allocation,
    dates,
    occupancy,
    mix,
    closures,
    capacity,
    scenario,
)


def run_checks(ctx: ValidationContext) -> None:
    """Run every hard-rule check in a deterministic order."""

    for module in CHECK_ORDER:
        module.check(ctx)


__all__ = ["CHECK_ORDER", "ValidationContext", "run_checks"]
