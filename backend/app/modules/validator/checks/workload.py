"""Workload conservation (rule ``workload``).

Every activity must be scheduled and its access yields must cover
``total_accesses`` in half-units: a standard night is 2 units and an ECLO night
is 3 units. Unknown activities are rejected too, because a submission that
invents work is not a valid answer to the instance.
"""

from __future__ import annotations

from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    known = ctx.known_activities
    scheduled: set[str] = set()
    for activity_id, rows in ctx.access_by_activity.items():
        if activity_id not in known:
            ctx.add("workload", f"unknown activity {activity_id!r} appears in SCHEDULE_ACCESS")
            continue
        if rows:
            scheduled.add(activity_id)
        activity = ctx.activity(activity_id)
        units = sum(3 if row.eclo else 2 for row in rows)
        required = 2 * activity.total_accesses
        if units < required:
            ctx.add(
                "workload",
                f"activity {activity_id} yields {units} half-units but needs {required} "
                f"({activity.total_accesses} accesses)",
            )

    for activity_id in sorted(known - scheduled):
        ctx.add("workload", f"activity {activity_id} is not scheduled")


__all__ = ["check"]
