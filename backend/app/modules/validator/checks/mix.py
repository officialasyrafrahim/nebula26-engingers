"""Legal possession mixes and co-share consistency (rule ``mix``).

A possession is one ``PM`` alone, one ``PC`` with at most three ``C``, or at
most four ``C``. The check runs at two granularities that must both hold:

* per ``(location, week, co_share_group)`` the labelled possession is a legal
  mix and every pair in it is co-share compatible;
* per ``(location, week, contract, activity_type, access_night)`` the activities
  forced onto one physical night by the local night namespace form a legal mix.
  ``access_night`` is contract/type-local, so two different contracts' night 1
  values are unrelated and are never combined here.
"""

from __future__ import annotations

from collections import defaultdict

from app.modules.compiler.mixes import co_share_compatible, legal_access_mix
from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    _check_groups(ctx)
    _check_night_classes(ctx)


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


def _check_night_classes(ctx: ValidationContext) -> None:
    occupants: dict[tuple[str, int, str, str, int], set[str]] = defaultdict(set)
    for (activity_id, week), locations in sorted(ctx.occupancy_locations.items()):
        if activity_id not in ctx.known_activities:
            continue
        access = ctx.access_row_at.get((activity_id, week))
        if access is None:
            continue
        contract = ctx.instance.contracts[ctx.activity(activity_id).contract_number]
        night = access.access_night
        for location_id in locations:
            occupants[
                (location_id, week, contract.contract_number, contract.activity_type, night)
            ].add(activity_id)

    for key, activities in sorted(occupants.items()):
        location_id, week, contract_number, activity_type, night = key
        known = sorted(activities)
        types = [ctx.activity(activity_id).access_type for activity_id in known]
        if not legal_access_mix(types):
            ctx.add(
                "mix",
                f"week {week} night {night} {location_id}: illegal simultaneous mix "
                f"{sorted(types)} from {known} "
                f"(contract {contract_number}/{activity_type})",
            )


__all__ = ["check"]
