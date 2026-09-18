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


def summarise_mix(access_types: Iterable[str]) -> dict[str, int]:
    """Return a deterministic count of each access type for diagnostics."""

    counts = _counts(access_types)
    return {access: counts.get(access, 0) for access in ACCESS_TYPES}
