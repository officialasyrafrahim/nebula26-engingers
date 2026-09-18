"""Physical possession-slot domain contract (F-COMPILER-002, AT-05/AT-06).

The compiled contract keeps ``access_night`` local to
``(contract_number, activity_type, week)`` and represents physical simultaneity
as an admissibility graph instead, because the published CSV schema exposes no
global night. The authoritative sample is the oracle: at
``SEC:BET:H01_H02:EB`` week 16 one co-share group ``b1`` spans local nights 1
and 3, so group identity and night identity are provably not interchangeable.
"""

from __future__ import annotations

import pytest

from app.modules.compiler.mixes import (
    legal_access_mix,
    minimum_possessions,
    pack_possessions,
)
from app.modules.compiler.rule_compiler import compile_instance
from tests.helpers_rail import (
    load_public_compiled,
    load_public_instance,
    sample_access_rows,
    sample_occupancy_rows,
)

LOCATION = "SEC:BET:H01_H02:EB"
WEEK = 16
GROUP = "b1"


def _sample_nights() -> dict[tuple[str, int], int]:
    return {
        (row["activity_id"], int(row["week"])): int(row["access_night"])
        for row in sample_access_rows()
    }


def test_access_night_domain_is_contract_type_local_and_week_scoped():
    compiled = load_public_compiled()
    contract = compiled.physical_possession

    c001 = contract.access_night_domain("C001", "Renewal", 1)
    c013 = contract.access_night_domain("C013", "Renewal", 1)
    assert c001.weekly_cap == 3 and c001.nights == (1, 2, 3)
    assert c013.weekly_cap == 2 and c013.nights == (1, 2)

    # Same numeric night, different contracts: distinct namespaces, never joined.
    assert c001.key != c013.key
    assert c001.week == c013.week == 1

    # Domain is scoped per week; the cap repeats but the key does not.
    c001_w2 = contract.access_night_domain("C001", "Renewal", 2)
    assert c001_w2.nights == c001.nights
    assert c001_w2.key != c001.key

    with pytest.raises(KeyError):
        contract.access_night_domain("C001", "Renewal", 999)


def test_authoritative_co_share_group_spans_different_local_nights():
    compiled = load_public_compiled()
    contract = compiled.physical_possession
    nights = _sample_nights()

    rows = [
        row
        for row in sample_occupancy_rows()
        if row["location_id"] == LOCATION
        and int(row["week"]) == WEEK
        and row["co_share_group"] == GROUP
    ]
    members = sorted(row["activity_id"] for row in rows)
    assert members == ["A003", "A007", "A040"]

    local_nights = {activity_id: nights[(activity_id, WEEK)] for activity_id in members}
    assert local_nights == {"A003": 3, "A007": 1, "A040": 1}
    assert len(set(local_nights.values())) > 1, "group must span local access nights"

    # The group is cross-contract and route-occupies the location.
    assert {compiled.activities[member].contract_number for member in members} == {
        "C001",
        "C007",
    }
    assert set(members) <= set(contract.occupants_at(LOCATION))

    types = [compiled.activities[member].access_type for member in members]
    assert types == ["C", "C", "C"]
    assert legal_access_mix(types)
    assert minimum_possessions(types) == 1

    # Canonical packing groups by possession, never by equal local night.
    packed = pack_possessions(
        (member, compiled.activities[member].access_type) for member in members
    )
    assert packed == (("A003", "A007", "A040"),)


def test_closure_conflict_graph_is_pure_and_waived_by_access_type():
    compiled = load_public_compiled()
    contract = compiled.physical_possession

    conflict = contract.closure_conflict("A003", "A007")
    assert conflict is not None
    assert conflict.rule == "closure"
    assert LOCATION in conflict.locations
    # Symmetric lookup uses the canonical pair key.
    assert contract.closure_conflict("A007", "A003") == conflict

    # The graph records the contention even though co-share compatible types
    # may still share one possession; the graph is a fact, the waiver is policy.
    assert contract.co_share_compatible("C", "C") is True
    assert contract.co_share_compatible("PC", "C") is True
    assert contract.co_share_compatible("PC", "PC") is False
    assert contract.co_share_compatible("PM", "C") is False

    assert contract.closure_conflict("A074", "A075") is not None
    assert contract.closure_conflict("A074", "A075").rule == "interchange"
    assert contract.closure_conflict("A003", "A500") is None


def test_location_occupants_exclude_buffer_only_closures():
    compiled = load_public_compiled()
    contract = compiled.physical_possession

    # A004 buffers into SEC:ALP:H01_H02:EB but its route does not occupy it.
    assert "SEC:ALP:H01_H02:EB" not in compiled.activities["A004"].occupied_locations
    assert "SEC:ALP:H01_H02:EB" in compiled.activities["A004"].closed_locations
    assert "A004" not in contract.occupants_at("SEC:ALP:H01_H02:EB")

    # A074's route starts on that location, so it does consume the capacity.
    assert "SEC:ALP:H01_H02:EB" in compiled.activities["A074"].occupied_locations
    assert "A074" in contract.occupants_at("SEC:ALP:H01_H02:EB")


def test_contract_is_attached_to_the_compiled_instance():
    compiled = compile_instance(load_public_instance())
    contract = compiled.physical_possession
    assert contract.co_share_allowed == compiled.co_share_allowed
    assert compiled.access_night_domain("C001", "Renewal", 1).weekly_cap == 3
    assert compiled.closure_conflict("A003", "A007") is not None


def test_minimum_possessions_counts_possessions_not_nights():
    assert minimum_possessions([]) == 0
    assert minimum_possessions(["PM"]) == 1
    assert minimum_possessions(["PM", "PM"]) == 2
    assert minimum_possessions(["PC"]) == 1
    assert minimum_possessions(["PC", "C", "C", "C"]) == 1
    assert minimum_possessions(["PC", "C", "C", "C", "C"]) == 2
    assert minimum_possessions(["PC", "PC"]) == 2
    assert minimum_possessions(["C", "C", "C", "C"]) == 1
    assert minimum_possessions(["C", "C", "C", "C", "C"]) == 2
    assert minimum_possessions({"PC": 1, "C": 3}) == 1


def test_pack_possessions_is_legal_and_meets_the_minimum():
    roster = [
        ("P1", "PM"),
        ("M1", "PC"),
        ("C1", "C"),
        ("C2", "C"),
        ("C3", "C"),
        ("C4", "C"),
        ("C5", "C"),
    ]
    groups = pack_possessions(roster)
    assert len(groups) == minimum_possessions([access_type for _, access_type in roster])
    assert all(legal_access_mix([dict(roster)[member] for member in group]) for group in groups)
    assert {member for group in groups for member in group} == {member for member, _ in roster}
