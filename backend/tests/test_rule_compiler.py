"""Rule compilation: buffers, mirroring, interchange, mixes and policy (AT-05/06)."""

from __future__ import annotations

import pytest

from app.modules.compiler.mixes import (
    build_co_share_allowed,
    co_share_compatible,
    legal_access_mix,
)
from app.modules.compiler.policy import (
    contract_overrun_weight,
    get_policy,
)
from app.modules.compiler.rule_compiler import compile_instance
from tests.helpers_rail import load_public_compiled, load_public_instance


def test_compiled_instance_matches_network_capacities():
    instance = load_public_instance()
    compiled = compile_instance(instance)
    assert len(compiled.activities) == len(instance.activities)
    assert compiled.location_capacities == {
        location_id: location.supply_capacity
        for location_id, location in instance.locations.items()
    }
    assert compiled.contract_weekly_caps["C013"] == 2
    assert compiled.contract_workfronts["C001"] == 2


def test_metadata_and_dependency_links():
    compiled = load_public_compiled()
    a004 = compiled.activities["A004"]
    assert a004.predecessor_activity_id == "A003"
    assert a004.planned_start_week == 15
    assert compiled.activities["A003"].planned_start_week == 11
    assert compiled.activities["A003"].successor_activity_ids == ("A004",)
    assert compiled.activities["A002"].predecessor_activity_id is None


def test_non_live_others_has_no_buffer():
    compiled = load_public_compiled()
    a014 = compiled.activities["A014"]
    assert a014.nature_of_activity == "Non-live (Others)"
    assert a014.buffer_sectors == 0
    assert set(a014.closure_locations) == set(a014.occupied_locations)


def test_non_live_consist_buffers_one_sector():
    compiled = load_public_compiled()
    a003 = compiled.activities["A003"]
    assert a003.buffer_sectors == 1
    assert "SEC:BET:H01_H02:EB" in a003.closure_locations
    assert "PLAT:BET:H01:EB" in a003.closure_locations
    assert a003.mirrored_locations == ()
    assert a003.interchange_locations == ()


def test_live_activity_mirrors_and_crosses_interchange():
    compiled = load_public_compiled()
    a074 = compiled.activities["A074"]
    assert a074.nature_of_activity == "Live"
    assert a074.opposite_bound_required is True
    assert "SEC:ALP:H01_H02:WB" in a074.mirrored_locations
    assert "PLAT:ALP:H01:WB" in a074.mirrored_locations
    assert set(a074.interchange_locations) == {
        "SEC:BET:H01_H02:EB",
        "PLAT:BET:H01:EB",
        "PLAT:BET:H02:EB",
        "SEC:BET:H01_H02:WB",
        "PLAT:BET:H01:WB",
        "PLAT:BET:H02:WB",
    }
    assert set(a074.closed_locations) == set(
        a074.closure_locations + a074.mirrored_locations + a074.interchange_locations
    )


def test_live_interchange_from_other_line():
    compiled = load_public_compiled()
    a075 = compiled.activities["A075"]
    assert "SEC:ALP:H01_H02:EB" in a075.interchange_locations
    assert "SEC:ALP:H01_H02:WB" in a075.interchange_locations


def test_non_live_work_never_crosses_lines():
    compiled = load_public_compiled()
    a003 = compiled.activities["A003"]
    assert not any(location.startswith("PLAT:ALP") for location in a003.closed_locations)
    assert not any(location.startswith("SEC:ALP") for location in a003.closed_locations)


def test_legal_access_mixes():
    assert legal_access_mix([]) is True
    assert legal_access_mix(["PM"]) is True
    assert legal_access_mix(["PM", "C"]) is False
    assert legal_access_mix(["PM", "PM"]) is False
    assert legal_access_mix(["PC"]) is True
    assert legal_access_mix(["PC", "C", "C", "C"]) is True
    assert legal_access_mix(["PC", "C", "C", "C", "C"]) is False
    assert legal_access_mix(["PC", "PC"]) is False
    assert legal_access_mix(["C", "C", "C", "C"]) is True
    assert legal_access_mix(["C", "C", "C", "C", "C"]) is False
    assert legal_access_mix({"PC": 1, "C": 3}) is True
    assert legal_access_mix({"PC": 1, "C": 4}) is False


def test_co_share_compatibility_table():
    assert co_share_compatible("PC", "C") is True
    assert co_share_compatible("C", "C") is True
    assert co_share_compatible("PC", "PC") is False
    assert co_share_compatible("PM", "C") is False
    assert co_share_compatible("PM", "PM") is False
    allowed = build_co_share_allowed()
    assert allowed[("C", "PC")] is True
    assert allowed[("PM", "PM")] is False
    assert set(allowed) == {
        ("C", "C"),
        ("C", "PC"),
        ("C", "PM"),
        ("PC", "PC"),
        ("PC", "PM"),
        ("PM", "PM"),
    }


def test_scenario_policy_matrix():
    policy_a = get_policy("A")
    assert policy_a.eclo_allowed is False
    assert policy_a.capacity_is_hard is True
    assert policy_a.hard_capacity_limit(4) == 4
    assert policy_a.overrun_scored is True
    assert policy_a.excess_access_nights_scored is False
    assert policy_a.eclo_window == "forbidden"

    policy_b = get_policy("B")
    assert policy_b.eclo_allowed is True
    assert policy_b.planned_completion_hard is True
    assert policy_b.capacity_mode == "soft_unbounded"
    assert policy_b.hard_capacity_limit(4) is None
    assert policy_b.eclo_window == "exempt"

    policy_c = get_policy("C")
    assert policy_c.capacity_mode == "soft_plus_one"
    assert policy_c.hard_capacity_limit(4) == 5
    assert policy_c.eclo_window == "two_week_per_line"
    assert policy_c.overrun_scored and policy_c.excess_access_nights_scored

    with pytest.raises(ValueError):
        get_policy("D")


def test_overrun_weight_bands():
    assert contract_overrun_weight(1, 3) == pytest.approx(100.0)
    assert contract_overrun_weight(1, 1) == pytest.approx(130.0)
    assert contract_overrun_weight(2, 1) == pytest.approx(13.0)
    assert contract_overrun_weight(3, 3) == pytest.approx(1.0)
