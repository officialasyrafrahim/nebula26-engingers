"""Closure, buffer, mirroring and interchange conflicts.

Published rule 4: an occupied worksite closes its span for the night and no
external activity may enter it; ``Live`` work mirrors onto the opposite bound and
crosses to the other line's ``H01_H02`` interchange. Published rule 6 exempts
co-sharing work from each other's closures.

Sample-consistent assumption (documented because the written rules are
ambiguous, see the design document section 19 A-1/A-2):

* two accesses are simultaneous iff they share ``(week, access_night)``;
* their compiled closure spans conflict when they intersect at a location;
* the conflict is waived exactly when the two access types are co-share
  compatible (``PC``+``C`` or ``C``+``C``), because rule 4/6 makes those
  buffer-free against each other.

The waiver is deliberately type-based rather than ``co_share_group``-based: the
published sample reuses group labels across nights (for example
``SEC:BET:H01_H02:EB`` week 16 group ``b1`` on nights 1 and 3), so group identity
cannot be the simultaneity key. The rule tag is the most specific component that
intersects: ``interchange`` beats ``mirror`` beats ``closure``.
"""

from __future__ import annotations

from app.modules.compiler.mixes import co_share_compatible
from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    for (week, night), activities in sorted(ctx.present_at_night.items()):
        known = sorted(a for a in activities if a in ctx.known_activities)
        for index, left in enumerate(known):
            left_activity = ctx.activity(left)
            for right in known[index + 1 :]:
                right_activity = ctx.activity(right)
                if co_share_compatible(
                    left_activity.access_type, right_activity.access_type
                ):
                    continue
                intersection = set(left_activity.closed_locations) & set(
                    right_activity.closed_locations
                )
                if not intersection:
                    continue
                rule = _rule_for(left_activity, right_activity, intersection)
                ctx.add(
                    rule,
                    f"week {week} night {night}: {left} {left_activity.access_type} "
                    f"and {right} {right_activity.access_type} conflict at "
                    f"{sorted(intersection)[:4]}",
                )


def _rule_for(left, right, intersection: set[str]) -> str:
    interchange = (set(left.interchange_locations) | set(right.interchange_locations))
    mirrored = set(left.mirrored_locations) | set(right.mirrored_locations)
    if intersection & interchange:
        return "interchange"
    if intersection & mirrored:
        return "mirror"
    return "closure"


__all__ = ["check"]
