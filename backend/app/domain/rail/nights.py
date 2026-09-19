"""The one shared physical-night universe for the rail model.

A planning week has exactly seven calendar nights. ``access_night`` stays a
contract/activity-type-local accounting index (design A-1/A-3); the physical
night is the global slot the solver assigns and the independent witness reads.

The solver, the fallback validator's physical check and the witness check must
all agree on this universe. They used to carry three private copies of ``7``, so
this module is the single source of truth. Nothing here depends on the model,
the compiler or a validator, which keeps the witness free of solver imports.
"""

from __future__ import annotations

PHYSICAL_NIGHTS_PER_WEEK = 7

PHYSICAL_NIGHT_SLOTS: tuple[int, ...] = tuple(range(1, PHYSICAL_NIGHTS_PER_WEEK + 1))

MIN_PHYSICAL_NIGHT = 1
MAX_PHYSICAL_NIGHT = PHYSICAL_NIGHTS_PER_WEEK


def in_physical_night_universe(night: int) -> bool:
    """Whether ``night`` is one of the seven physical slots."""

    return MIN_PHYSICAL_NIGHT <= night <= MAX_PHYSICAL_NIGHT


__all__ = [
    "MAX_PHYSICAL_NIGHT",
    "MIN_PHYSICAL_NIGHT",
    "PHYSICAL_NIGHTS_PER_WEEK",
    "PHYSICAL_NIGHT_SLOTS",
    "in_physical_night_universe",
]
