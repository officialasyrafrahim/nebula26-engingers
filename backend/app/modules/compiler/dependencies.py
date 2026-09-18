"""Predecessor / successor link compilation.

Rule 3: finish-to-start with zero lag. Links may cross contracts, cycles are
rejected at ingest. This module only exposes the derived link structures; the
week-offset constraint itself belongs to the solver.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.rail.instance_model import (
    Activity,
    build_successor_index,
    find_predecessor_cycles,
)


def build_dependency_maps(
    activities: Mapping[str, Activity],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Return ``(predecessors, successors)`` for the given activities."""

    predecessors = {
        activity_id: activity.predecessor_activity_id
        for activity_id, activity in activities.items()
        if activity.predecessor_activity_id is not None
    }
    return predecessors, build_successor_index(predecessors)


def predecessor_cycle(activities: Mapping[str, Activity]) -> tuple[str, ...] | None:
    """Return the first predecessor cycle, if any."""

    predecessors, _ = build_dependency_maps(activities)
    cycles = find_predecessor_cycles(predecessors)
    return cycles[0] if cycles else None
