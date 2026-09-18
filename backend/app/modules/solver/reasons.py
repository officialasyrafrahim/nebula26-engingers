"""Stable solver reason codes.

The solver publishes a per-activity reason set on
``SolverResult.binding_reasons``. The worker persists that mapping on
``ScenarioJob.result['binding_reasons']`` and DEV-4 renders it without a
translation layer, so these names are a frozen contract: add codes, never rename
one that has shipped.

Codes cover the hard rules the solver models (planned start, predecessor,
weekly cap, workfront, ECLO window, horizon, capacity) and the physical
possession facts needed to explain displaced work (buffer closure, Live
mirroring, interchange, possession mix and co-sharing).
"""

from __future__ import annotations

PLANNED_START = "PLANNED_START"
PREDECESSOR = "PREDECESSOR"
WEEKLY_CAP = "WEEKLY_CAP"
WORKFRONT = "WORKFRONT"
ECLO_WINDOW = "ECLO_WINDOW"
PRIORITY_OVERRUN = "PRIORITY_OVERRUN"
HORIZON_EXTENDED = "HORIZON_EXTENDED"
CAPACITY = "CAPACITY"
CO_SHARE_PACKED = "CO_SHARE_PACKED"
POSSESSION_MIX = "POSSESSION_MIX"
BUFFER_CLOSURE = "BUFFER_CLOSURE"
LIVE_MIRROR = "LIVE_MIRROR"
INTERCHANGE = "INTERCHANGE"

ALL_REASON_CODES: tuple[str, ...] = (
    PLANNED_START,
    PREDECESSOR,
    WEEKLY_CAP,
    WORKFRONT,
    ECLO_WINDOW,
    PRIORITY_OVERRUN,
    HORIZON_EXTENDED,
    CAPACITY,
    CO_SHARE_PACKED,
    POSSESSION_MIX,
    BUFFER_CLOSURE,
    LIVE_MIRROR,
    INTERCHANGE,
)

# Maps a compiled ``ClosureConflict.rule`` to the reason code it explains.
CLOSURE_RULE_CODES: dict[str, str] = {
    "closure": BUFFER_CLOSURE,
    "mirror": LIVE_MIRROR,
    "interchange": INTERCHANGE,
}

__all__ = [
    "ALL_REASON_CODES",
    "BUFFER_CLOSURE",
    "CAPACITY",
    "CLOSURE_RULE_CODES",
    "CO_SHARE_PACKED",
    "ECLO_WINDOW",
    "HORIZON_EXTENDED",
    "INTERCHANGE",
    "LIVE_MIRROR",
    "PLANNED_START",
    "POSSESSION_MIX",
    "PREDECESSOR",
    "PRIORITY_OVERRUN",
    "WEEKLY_CAP",
    "WORKFRONT",
]
