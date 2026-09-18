"""Closure, buffer, mirroring and interchange conflicts.

Published rule 4: an occupied worksite closes its span for the night and no
external activity may enter it; ``Live`` work mirrors onto the opposite bound and
crosses to the other line's ``H01_H02`` interchange. Published rule 6 exempts
co-sharing work from each other's closures.

``access_night`` is contract/activity-type-local, so the submission does not
encode a global physical night and matching numbers across contracts are **not**
simultaneity. This check therefore delegates to
:mod:`app.modules.validator.checks.physical`, which validates that a consistent
physical-night assignment exists for every week using the compiled
``PhysicalPossessionContract.closure_conflicts`` graph. A conflict is reported
only when the classes forced onto one night (same contract/type/week/night) are
incompatible, or when no 7-night assignment can separate the conflict graph.
"""

from __future__ import annotations

from app.modules.validator.checks import physical
from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    physical.check(ctx)


__all__ = ["check"]
