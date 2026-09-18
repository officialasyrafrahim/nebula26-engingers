"""Weekly allocation and workfront caps (rules ``allocation`` and ``workfront``).

``access_seq`` must be a contiguous 1..n sequence following ``(week,
access_night)``. No activity may take two accesses in one week, and its
``access_night`` must sit inside the contract's granted nights. Per
``(contract, activity_type, week)`` the number of distinct nights cannot exceed
``number_of_maximum_access_per_week``; per
``(contract, activity_type, week, access_night)`` the number of distinct
activities cannot exceed ``number_of_workfronts``.
"""

from __future__ import annotations

from collections import defaultdict

from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    _check_access_structure(ctx)
    _check_weekly_caps(ctx)
    _check_workfronts(ctx)


def _check_access_structure(ctx: ValidationContext) -> None:
    for activity_id, rows in sorted(ctx.access_by_activity.items()):
        if activity_id not in ctx.known_activities:
            continue
        contract = ctx.instance.contracts[ctx.activity(activity_id).contract_number]
        cap = contract.number_of_maximum_access_per_week

        sequences = sorted(row.access_seq for row in rows)
        if sequences != list(range(1, len(rows) + 1)):
            ctx.add(
                "allocation",
                f"activity {activity_id} access_seq is not contiguous 1..{len(rows)}: "
                f"{sequences}",
            )

        weeks = [row.week for row in rows]
        if len(weeks) != len(set(weeks)):
            ctx.add(
                "allocation",
                f"activity {activity_id} has more than one access in the same week: {weeks}",
            )

        ordered = sorted(rows, key=lambda row: (row.week, row.access_night))
        for expected, row in enumerate(ordered, start=1):
            if row.access_seq != expected:
                ctx.add(
                    "allocation",
                    f"activity {activity_id} access_seq does not follow (week, access_night) "
                    f"order at seq {row.access_seq}",
                )
                break

        for row in rows:
            if not 1 <= row.access_night <= cap:
                ctx.add(
                    "allocation",
                    f"activity {activity_id} week {row.week} access_night "
                    f"{row.access_night} is outside 1..{cap}",
                )


def _check_weekly_caps(ctx: ValidationContext) -> None:
    nights: dict[tuple[str, str, int], set[int]] = defaultdict(set)
    for activity_id, rows in ctx.access_by_activity.items():
        if activity_id not in ctx.known_activities:
            continue
        activity = ctx.activity(activity_id)
        instance_activity = ctx.instance.activities[activity_id]
        for row in rows:
            nights[
                (activity.contract_number, instance_activity.activity_type, row.week)
            ].add(row.access_night)

    for (contract_number, _activity_type, week), used in sorted(nights.items()):
        cap = ctx.instance.contracts[contract_number].number_of_maximum_access_per_week
        if len(used) > cap:
            ctx.add(
                "allocation",
                f"contract {contract_number} uses {len(used)} distinct access nights in "
                f"week {week} but the weekly cap is {cap}",
            )


def _check_workfronts(ctx: ValidationContext) -> None:
    participants: dict[tuple[str, str, int, int], set[str]] = defaultdict(set)
    for activity_id, rows in ctx.access_by_activity.items():
        if activity_id not in ctx.known_activities:
            continue
        activity = ctx.activity(activity_id)
        activity_type = ctx.instance.activities[activity_id].activity_type
        for row in rows:
            key = (
                activity.contract_number,
                activity_type,
                row.week,
                row.access_night,
            )
            participants[key].add(activity_id)

    for (contract_number, activity_type, week, night), activities in sorted(
        participants.items()
    ):
        workfronts = ctx.instance.contracts[contract_number].number_of_workfronts
        if len(activities) > workfronts:
            ctx.add(
                "workfront",
                f"contract {contract_number} type {activity_type} runs "
                f"{len(activities)} activities on week {week} night {night} but the "
                f"workfront cap is {workfronts}: {sorted(activities)}",
            )


__all__ = ["check"]
