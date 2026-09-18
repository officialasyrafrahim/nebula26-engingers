"""Legal possession mixes and co-share consistency (rule ``mix``).

A possession is one ``PM`` alone, one ``PC`` with at most three ``C``, or at
most four ``C``. The check runs at two granularities that must both hold:

* per ``(location, week, co_share_group)`` the labelled possession is a legal
  mix and every pair in it is co-share compatible;
* per ``(location, week, access_night)`` the simultaneous occupants form a
  legal mix, so incompatible work cannot hide behind different group labels.
"""

from __future__ import annotations

from collections import defaultdict

from app.modules.compiler.mixes import co_share_compatible, legal_access_mix
from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    _check_groups(ctx)
    _check_night_mixes(ctx)


def _check_groups(ctx: ValidationContext) -> None:
    for (location_id, week, group), activities in sorted(ctx.group_activities.items()):
        known = sorted(a for a in activities if a in ctx.known_activities)
        if not known:
            continue
        types = [ctx.activity(activity_id).access_type for activity_id in known]
        if not legal_access_mix(types):
            ctx.add(
                "mix",
                f"week {week} {location_id} group {group}: illegal possession mix "
                f"{sorted(types)} from {known}",
            )
            continue
        for index, left in enumerate(known):
            for right in known[index + 1 :]:
                if not co_share_compatible(
                    ctx.activity(left).access_type, ctx.activity(right).access_type
                ):
                    ctx.add(
                        "mix",
                        f"week {week} {location_id} group {group}: {left} and {right} "
                        f"cannot co-share "
                        f"({ctx.activity(left).access_type}/{ctx.activity(right).access_type})",
                    )


def _check_night_mixes(ctx: ValidationContext) -> None:
    occupants: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for (week, night), activities in ctx.present_at_night.items():
        for activity_id in activities:
            if activity_id not in ctx.known_activities:
                continue
            for location_id in ctx.activity(activity_id).occupied_locations:
                occupants[(location_id, week, night)].add(activity_id)

    for (location_id, week, night), activities in sorted(occupants.items()):
        known = sorted(activities)
        types = [ctx.activity(activity_id).access_type for activity_id in known]
        if not legal_access_mix(types):
            ctx.add(
                "mix",
                f"week {week} night {night} {location_id}: illegal simultaneous mix "
                f"{sorted(types)} from {known}",
            )


__all__ = ["check"]
