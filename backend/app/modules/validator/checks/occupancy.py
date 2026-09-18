"""Occupancy exactness (rule ``occupancy``).

``SCHEDULE_OCCUPANCY.csv`` is the physical footprint of each access. For every
activity-week that has an access, the set of occupied locations must equal the
activity's expanded route exactly: no missing sector, no extra location and no
occupancy row for a week with no access. Live mirroring and interchange effects
are closure constraints, never occupancy rows.
"""

from __future__ import annotations

from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    _check_unknown_activities(ctx)
    _check_exact_route(ctx)
    _check_orphan_weeks(ctx)


def _route(ctx: ValidationContext, activity_id: str) -> frozenset[str]:
    return frozenset(ctx.activity(activity_id).occupied_locations)


def _check_unknown_activities(ctx: ValidationContext) -> None:
    for activity_id, week in sorted(ctx.occupancy_locations):
        if activity_id not in ctx.known_activities:
            ctx.add(
                "occupancy",
                f"unknown activity {activity_id!r} appears in SCHEDULE_OCCUPANCY week {week}",
            )


def _check_exact_route(ctx: ValidationContext) -> None:
    for activity_id, rows in sorted(ctx.access_by_activity.items()):
        if activity_id not in ctx.known_activities:
            continue
        route = _route(ctx, activity_id)
        weeks = {row.week for row in rows}
        for week in sorted(weeks):
            occupied = ctx.occupancy_locations.get((activity_id, week), set())
            missing = sorted(route - occupied)
            extra = sorted(occupied - route)
            if missing or extra:
                detail = [f"activity {activity_id} week {week}"]
                if missing:
                    detail.append(f"missing {missing[:4]}")
                if extra:
                    detail.append(f"unexpected {extra[:4]}")
                ctx.add("occupancy", " ".join(detail))


def _check_orphan_weeks(ctx: ValidationContext) -> None:
    for activity_id, week in sorted(ctx.occupancy_locations):
        if activity_id not in ctx.known_activities:
            continue
        if (activity_id, week) not in ctx.access_row_at:
            ctx.add(
                "occupancy",
                f"activity {activity_id} occupies week {week} without a matching access",
            )


__all__ = ["check"]
