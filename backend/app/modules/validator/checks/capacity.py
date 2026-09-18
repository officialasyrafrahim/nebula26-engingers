"""Location-week capacity from the published supply (rule ``capacity``).

Capacity is counted as the number of distinct ``co_share_group`` values at a
``(location, week)``. The hard ceiling follows the scenario policy: Scenario A
allows exactly ``supply_capacity``; Scenario C allows one extra possession
before hard-failing (the soft-scored elasticity); Scenario B is unbounded and
only contributes to the excess score.
"""

from __future__ import annotations

from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    for (location_id, week), groups in sorted(ctx.groups_at_location_week.items()):
        location = ctx.instance.locations.get(location_id)
        if location is None:
            continue
        capacity = location.supply_capacity
        used = len(groups)
        excess = max(0, used - capacity)
        ctx.capacity_excess[(location_id, week)] = excess
        ctx.excess_access_nights_total += excess
        if excess > 0:
            ctx.capacity_hotspots.append(
                {
                    "location_id": location_id,
                    "week": week,
                    "used": used,
                    "capacity": capacity,
                    "excess": excess,
                }
            )
        limit = ctx.policy.hard_capacity_limit(capacity)
        if limit is not None and used > limit:
            ctx.add(
                "capacity",
                f"week {week} {location_id}: {used} possessions exceed the "
                f"{ctx.scenario}-scenario limit {limit} (supply {capacity})",
            )


__all__ = ["check"]
