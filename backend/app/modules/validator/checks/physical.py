"""Physical possession-slot admissibility for fallback validation.

``access_night`` is contract/activity-type-local, so equal local night numbers in
two contracts are never the same physical fact. The submission does not publish
a global physical night, so the fallback checks that a consistent assignment
exists instead of inventing one.

Equivalence classes are the contract/type/week/local-night namespaces (one
physical slot each). Distinct local nights in one contract/type/week must map to
distinct slots. Two activities in the **same** class are forced onto one
physical slot. When their access types cannot co-share, a compiled closure,
mirror or interchange conflict between them is provable and rejected even when
their occupied routes do not intersect (only their buffers do). When their types
are co-share compatible but their routes are disjoint, local-night identity
alone does not prove they meet, so the buffer-only overlap stays provisional.
Two activities in **different** classes are only known to be simultaneous when
they share an occupied route location that week, where the submitted group
structure can prove they meet; then their slots must differ. A cross-class pair
whose only overlap is a buffer carries no proof either way and stays
provisional. The remaining class graph must be 7-colourable (a week has exactly
seven calendar nights). A closure pair is waived when it shares a submitted
``co_share_group`` at a common occupied location; type compatibility alone never
waives a buffer or closure.

Deliberate, sample-calibrated limitation (pending the official validator,
F-VALIDATOR-004): location-scoped ``co_share_group`` labels are **not** composed
into a transitive global physical-night identity. The authoritative public
sample carries different group labels along one activity's route and one group
across different local access-night indices, so a global group equivalence would
reject a submission the reference validator accepts. The group is therefore used
only to waive an explicitly co-shared closure pair, never to infer global
equality or global inequality. The official report may still diverge; the
fallback never claims official parity.
"""

from __future__ import annotations

import itertools
from collections import defaultdict

from app.domain.rail.nights import PHYSICAL_NIGHTS_PER_WEEK
from app.modules.compiler.mixes import co_share_compatible
from app.modules.validator.checks.context import ValidationContext

_RULE_SEVERITY = {
    "interchange": 5,
    "mirror": 4,
    "closure": 3,
}


def _class_key(ctx: ValidationContext, activity_id: str, week: int) -> tuple:
    contract = ctx.instance.contracts[ctx.activity(activity_id).contract_number]
    night = ctx.access_row_at[(activity_id, week)].access_night
    return (contract.contract_number, contract.activity_type, week, night)


def _conflicts_by_activity(ctx: ValidationContext) -> dict[str, list[tuple[str, str]]]:
    """Bucket compiled closure conflicts by activity id with their rule tag."""

    conflicts: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (left, right), conflict in (
        ctx.compiled.physical_possession.closure_conflicts.items()
    ):
        conflicts[left].append((right, conflict.rule))
        conflicts[right].append((left, conflict.rule))
    return conflicts


def _group_of(ctx: ValidationContext, week: int) -> dict[tuple[str, str], str]:
    """Submitted group per ``(activity_id, location_id)`` for one week."""

    groups: dict[tuple[str, str], str] = {}
    for (location_id, group_week, group), members in ctx.group_activities.items():
        if group_week != week:
            continue
        for activity_id in members:
            if activity_id in ctx.known_activities:
                groups.setdefault((activity_id, location_id), group)
    return groups


def _shares_group_at_common_location(
    ctx: ValidationContext,
    week: int,
    left: str,
    right: str,
    groups: dict[tuple[str, str], str],
) -> bool:
    """Rule 6/4 waiver: the pair is explicitly one possession at a shared spot."""

    left_locations = ctx.occupancy_locations.get((left, week), set())
    right_locations = ctx.occupancy_locations.get((right, week), set())
    for location_id in left_locations & right_locations:
        left_group = groups.get((left, location_id))
        right_group = groups.get((right, location_id))
        if left_group is not None and left_group == right_group:
            return True
    return False


def _colour_classes(adjacency: list[set[int]], component: list[int], colours: int) -> bool:
    """Exact DSATUR colouring of one connected component."""

    if len(component) <= 1:
        return True
    ordered = sorted(component, key=lambda node: (-len(adjacency[node]), node))
    colour: dict[int, int] = {}

    def backtrack(position: int) -> bool:
        if position == len(ordered):
            return True
        node = ordered[position]
        used = {colour[n] for n in adjacency[node] if n in colour}
        for candidate in range(colours):
            if candidate in used:
                continue
            colour[node] = candidate
            if backtrack(position + 1):
                return True
            del colour[node]
        return False

    return backtrack(0)


def _components(adjacency: list[set[int]], count: int) -> list[list[int]]:
    seen: set[int] = set()
    result: list[list[int]] = []
    for start in range(count):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: list[int] = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbour in adjacency[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        result.append(sorted(component))
    return result


def check(ctx: ValidationContext) -> None:
    """Check 7-night closure admissibility over local-night classes."""

    conflicts_by_activity = _conflicts_by_activity(ctx)
    accesses_by_week: dict[int, list[str]] = defaultdict(list)
    for activity_id, week in sorted(ctx.access_row_at):
        if activity_id in ctx.known_activities:
            accesses_by_week[week].append(activity_id)

    for week in sorted(accesses_by_week):
        _check_week(ctx, week, sorted(accesses_by_week[week]), conflicts_by_activity)


def _check_week(
    ctx: ValidationContext,
    week: int,
    activities: list[str],
    conflicts_by_activity: dict[str, list[tuple[str, str]]],
) -> None:
    keys: list[tuple] = []
    index: dict[tuple, int] = {}
    node_of: dict[str, int] = {}
    for activity_id in activities:
        key = _class_key(ctx, activity_id, week)
        node = index.get(key)
        if node is None:
            node = len(keys)
            keys.append(key)
            index[key] = node
        node_of[activity_id] = node

    adjacency: list[set[int]] = [set() for _ in keys]

    def require_different(left: int, right: int) -> None:
        if left == right:
            return
        adjacency[left].add(right)
        adjacency[right].add(left)

    # Contract/type/week/local-night classes: distinct local nights are distinct
    # physical slots.
    namespaces: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for key, node in index.items():
        namespaces[(key[0], key[1], key[2])].append(node)
    for nodes in namespaces.values():
        for left, right in itertools.combinations(sorted(nodes), 2):
            require_different(left, right)

    groups = _group_of(ctx, week)
    present = set(activities)
    occupied = {
        activity_id: frozenset(ctx.activity(activity_id).occupied_locations)
        for activity_id in activities
    }
    forced: list[tuple[str, str, str]] = []
    separations: list[tuple[str, str, str]] = []
    for left in activities:
        for right, rule in conflicts_by_activity.get(left, ()):
            if right not in present or right <= left:
                continue
            if _shares_group_at_common_location(ctx, week, left, right, groups):
                continue
            same_class = node_of[left] == node_of[right]
            co_shareable = co_share_compatible(
                ctx.activity(left).access_type, ctx.activity(right).access_type
            )
            if same_class and (not co_shareable or occupied[left] & occupied[right]):
                # Same contract/type/week/local-night class: the pair is forced
                # onto one physical slot. An incompatibly-typed pair is provably
                # in conflict even when the occupied routes do not intersect, so
                # buffer-only overlaps of closures, mirrors and interchanges are
                # rejected. A co-share compatible pair with disjoint routes stays
                # provisional because local-night identity alone does not prove
                # that two compatible activities meet (the authoritative sample
                # depends on this).
                forced.append((left, right, rule))
            elif not same_class and occupied[left] & occupied[right]:
                # Different classes with a shared occupied route location: the
                # pair can be simultaneous, so their slots must differ.
                separations.append((left, right, rule))
            # Otherwise the only overlap is a buffer across unrelated local-night
            # namespaces, or across co-share compatible types with disjoint
            # routes. The published schema cannot prove simultaneity, so the pair
            # stays provisional and is not separated.

    if forced:
        for left, right, rule in forced:
            ctx.add(
                rule,
                f"week {week}: {left} and {right} are the same "
                f"contract/type/week/local-night class but their {rule} spans "
                "conflict and they do not share a possession",
            )
        return

    for left, right, _rule in separations:
        require_different(node_of[left], node_of[right])

    for component in _components(adjacency, len(keys)):
        if _colour_classes(adjacency, component, PHYSICAL_NIGHTS_PER_WEEK):
            continue
        component_set = set(component)
        rules = [
            rule
            for left, right, rule in separations
            if node_of[left] in component_set
        ]
        rule = max(rules, key=lambda item: _RULE_SEVERITY[item]) if rules else "closure"
        ctx.add(
            rule,
            f"week {week}: closures of {len(component)} local-night classes cannot "
            f"be separated within {PHYSICAL_NIGHTS_PER_WEEK} physical nights",
        )


__all__ = ["PHYSICAL_NIGHTS_PER_WEEK", "check"]
