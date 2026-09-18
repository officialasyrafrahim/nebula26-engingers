"""Planned start and finish-to-start predecessor precedence.

Rule ``planned_start``: no access before the week containing the activity's
``planned_start_date``. Rule ``predecessor``: the successor's first access week
must be strictly later than the predecessor's last access week (FS+0, cross
contract allowed).
"""

from __future__ import annotations

from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    _check_planned_start(ctx)
    _check_predecessors(ctx)


def _first_week(ctx: ValidationContext, activity_id: str) -> int | None:
    rows = ctx.access_by_activity.get(activity_id)
    if not rows:
        return None
    return min(row.week for row in rows)


def _last_week(ctx: ValidationContext, activity_id: str) -> int | None:
    rows = ctx.access_by_activity.get(activity_id)
    if not rows:
        return None
    return max(row.week for row in rows)


def _check_planned_start(ctx: ValidationContext) -> None:
    for activity_id in sorted(ctx.known_activities):
        first_week = _first_week(ctx, activity_id)
        if first_week is None:
            continue
        earliest = ctx.activity(activity_id).planned_start_week
        if first_week < earliest:
            ctx.add(
                "planned_start",
                f"activity {activity_id} starts week {first_week} before its planned "
                f"start week {earliest}",
            )


def _check_predecessors(ctx: ValidationContext) -> None:
    for activity_id in sorted(ctx.known_activities):
        predecessor_id = ctx.activity(activity_id).predecessor_activity_id
        if predecessor_id is None:
            continue
        first_week = _first_week(ctx, activity_id)
        predecessor_last = _last_week(ctx, predecessor_id)
        if first_week is None or predecessor_last is None:
            continue
        if first_week <= predecessor_last:
            ctx.add(
                "predecessor",
                f"activity {activity_id} starts week {first_week} but predecessor "
                f"{predecessor_id} does not finish until week {predecessor_last} "
                "(FS+0 violated)",
            )


__all__ = ["check"]
