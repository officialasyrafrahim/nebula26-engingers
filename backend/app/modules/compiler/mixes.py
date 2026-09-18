"""Legal possession mixes and co-sharing compatibility.

Published rule 5/6: a location-night holds exactly one possession, which is
either one ``PM`` alone, one ``PC`` with up to three ``C`` co-workers, or up to
four ``C`` co-workers. Same ``(location, week, co_share_group)`` activities are
one possession and are exempt from each other's buffers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from itertools import combinations_with_replacement

ACCESS_TYPES: tuple[str, ...] = ("PM", "PC", "C")
PC_COWORKER_LIMIT = 3
C_ONLY_LIMIT = 4


def _counts(access_types: Mapping[str, int] | Iterable[str]) -> Counter[str]:
    counts = Counter(access_types)
    return Counter({access: count for access, count in counts.items() if count})


def legal_access_mix(access_types: Mapping[str, int] | Iterable[str]) -> bool:
    """Return whether the access types form one legal possession at a location.

    An empty set is treated as vacuously legal so callers can test incremental
    additions without special-casing the first activity.
    """

    counts = _counts(access_types)
    if not counts:
        return True
    if set(counts) == {"PM"}:
        return counts["PM"] == 1
    if "PM" in counts:
        return False
    if set(counts) > {"PC", "C"}:
        return False
    if counts.get("PC", 0) > 1:
        return False
    if counts.get("PC", 0) == 1:
        return counts.get("C", 0) <= PC_COWORKER_LIMIT
    return counts["C"] <= C_ONLY_LIMIT


def co_share_compatible(left: str, right: str) -> bool:
    """Whether two access types may share one ``co_share_group``."""

    if left not in ACCESS_TYPES or right not in ACCESS_TYPES:
        return False
    pair = {left, right}
    return pair <= {"C"} or pair == {"PC", "C"}


def build_co_share_allowed() -> dict[tuple[str, str], bool]:
    """Build the unordered access-type compatibility table."""

    return {
        tuple(sorted(pair)): co_share_compatible(*pair)
        for pair in combinations_with_replacement(ACCESS_TYPES, 2)
    }


def possession_slot_count(access_types: Iterable[str]) -> int:
    """Number of distinct possession slots used; legal mixes always return 1."""

    return 1 if _counts(access_types) else 0


def minimum_possessions(access_types: Mapping[str, int] | Iterable[str]) -> int:
    """Minimum legal possessions needed to host a whole location-week roster.

    ``PM`` is always alone; each ``PC`` hosts up to three ``C``; remaining ``C``
    pack four to a possession:

        possessions = pm + max(pc, ceil((pc + c) / 4))

    For a single legal possession this returns 1. Callers use it to compare the
    capacity a location-week consumes against ``supply_capacity`` without
    depending on how ``co_share_group`` labels were assigned.
    """

    counts = _counts(access_types)
    pm = counts.get("PM", 0)
    pc = counts.get("PC", 0)
    coworker = counts.get("C", 0)
    return pm + max(pc, -(-(pc + coworker) // C_ONLY_LIMIT))


def pack_possessions(
    roster: Iterable[tuple[str, str]],
) -> tuple[tuple[str, ...], ...]:
    """Deterministically pack ``(activity_id, access_type)`` into legal possessions.

    Input order is preserved. Every group is a legal possession mix: one ``PM``;
    one ``PC`` with up to three ``C``; or up to four ``C``. This is the single
    canonical grouping a solver may emit as ``co_share_group`` labels and a
    fallback validator may reconstruct to compare possession counts. Unrecognised
    types each take their own group so no occupant is silently dropped.
    """

    pms: list[str] = []
    pcs: list[str] = []
    coworkers: list[str] = []
    others: list[str] = []
    for activity_id, access_type in roster:
        if access_type == "PM":
            pms.append(activity_id)
        elif access_type == "PC":
            pcs.append(activity_id)
        elif access_type == "C":
            coworkers.append(activity_id)
        else:
            others.append(activity_id)

    groups: list[tuple[str, ...]] = [(activity_id,) for activity_id in pms]
    next_coworker = 0
    for pc in pcs:
        members = [pc]
        while len(members) < PC_COWORKER_LIMIT + 1 and next_coworker < len(coworkers):
            members.append(coworkers[next_coworker])
            next_coworker += 1
        groups.append(tuple(members))
    for start in range(next_coworker, len(coworkers), C_ONLY_LIMIT):
        groups.append(tuple(coworkers[start : start + C_ONLY_LIMIT]))
    groups.extend((activity_id,) for activity_id in others)
    return tuple(groups)


def summarise_mix(access_types: Iterable[str]) -> dict[str, int]:
    """Return a deterministic count of each access type for diagnostics."""

    counts = _counts(access_types)
    return {access: counts.get(access, 0) for access in ACCESS_TYPES}
