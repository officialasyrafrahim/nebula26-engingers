"""Physical possession-slot helpers shared by solver constraints and reasons.

Published PS1 rules 5 and 6 scope a possession to
``(location_id, week, co_share_group)`` on one access-night slot. Different
groups at the same location-week are different nights, and closure waivers apply
only to work that is actually in the same group. The solver therefore represents
a possession as a physical night at a location-week.
"""

from __future__ import annotations

from app.domain.rail.compiled import CompiledInstance


def truly_co_sharable(
    compiled: CompiledInstance, left_id: str, right_id: str
) -> bool:
    """Whether two activities may share one physical possession.

    Rule 6 waives a conflict only for work in the same possession. That requires
    co-share-compatible access types and at least one occupied route location
    where the per-slot mix constraints can place both activities in the same
    group. A type-compatible pair whose occupied routes are disjoint interacts
    only through a buffer and cannot share a possession, so it must stay on
    separate physical nights.
    """

    possession = compiled.physical_possession
    left = compiled.activities[left_id]
    right = compiled.activities[right_id]
    if not possession.co_share_compatible(left.access_type, right.access_type):
        return False
    return bool(frozenset(left.occupied_locations) & frozenset(right.occupied_locations))


__all__ = ["truly_co_sharable"]
