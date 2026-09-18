"""Solver physical possession-slot behaviour (F-SOLVER-007, AT-05/AT-06).

``access_night`` is contract/activity-type-local, so the solver must not treat
equal local night numbers in two contracts as the same physical fact. These
tests pin the physical-night model the solver now uses: closures, mirroring,
interchange and mix legality are enforced on a global physical night, while
capacity and co-sharing are counted as ``co_share_group`` possessions.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.rail.network import BufferRule
from app.modules.compiler.rule_compiler import compile_instance
from app.modules.solver import cp_sat_available, reasons, solve
from tests.test_rail_solver import (
    BUFFER_RULES,
    HORIZON_START,
    activity_access,
    location_positions,
    make_compiled,
    make_planning,
)

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"
NEXT_SECTOR = "SEC:ALP:H01_H02:EB"


def _access(**overrides):
    data = {
        "start_location_id": SECTOR,
        "end_location_id": SECTOR,
        "total_accesses": 1,
    }
    data.update(overrides)
    return data


def _contract(contract_number: str, **overrides):
    data = {
        "contract_number": contract_number,
        "access_type": "C",
        "nature_of_activity": "Non-live (Others)",
    }
    data.update(overrides)
    return data


def _physical_nights(result, activity_id: str) -> set[tuple[int, int | None]]:
    return {
        (row.week, row.physical_night)
        for row in result.access
        if row.activity_id == activity_id
    }


def test_incompatible_contracts_share_local_night_but_not_physical_night():
    """Same local ``access_night`` is allowed; the physical night is not.

    Both contracts default to ``access_night`` 1 because each ranks its own
    granted nights. The compiled closure overlap forces different physical
    nights, which is what the fallback's 7-colour check reads.
    """

    compiled = make_compiled(
        [
            _contract("C1", access_type="PC", nature_of_activity="Non-live (Consist)"),
            _contract("C2", access_type="PC", nature_of_activity="Non-live (Consist)"),
        ],
        [
            _access(activity_id="A1", contract_number="C1"),
            _access(
                activity_id="A2",
                contract_number="C2",
                start_location_id=NEXT_SECTOR,
                end_location_id=NEXT_SECTOR,
            ),
        ],
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1").isdisjoint(_physical_nights(result, "A2"))
    assert all(1 <= row.access_night <= 3 for row in result.access)
    assert reasons.BUFFER_CLOSURE in result.binding_reasons["A1"]
    assert reasons.BUFFER_CLOSURE in result.binding_reasons["A2"]


def test_live_mirroring_conflict_is_a_physical_night_separation():
    # A one-sector Live buffer keeps the closure off H01_H02, so the conflict is
    # tagged as mirroring rather than interchange on the tiny test network.
    base = make_planning(
        [
            _contract("C1", access_type="PC", nature_of_activity="Live"),
            _contract("C2", access_type="PC", nature_of_activity="Live"),
        ],
        [
            _access(
                activity_id="A1",
                contract_number="C1",
                start_location_id="SEC:ALP:S01_S02:EB",
                end_location_id="SEC:ALP:S01_S02:EB",
            ),
            _access(
                activity_id="A2",
                contract_number="C2",
                start_location_id="SEC:ALP:S01_S02:WB",
                end_location_id="SEC:ALP:S01_S02:WB",
            ),
        ],
        horizon_weeks=1,
    )
    rules = dict(BUFFER_RULES)
    rules["Live"] = BufferRule(
        nature_of_works="Live", up_to_buffer_sectors=1, opposite_bound_required=True
    )
    compiled = compile_instance(base.model_copy(update={"buffer_rules": rules}))
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1").isdisjoint(_physical_nights(result, "A2"))
    assert reasons.LIVE_MIRROR in result.binding_reasons["A1"]
    assert reasons.LIVE_MIRROR in result.binding_reasons["A2"]


def test_live_interchange_conflict_is_a_physical_night_separation():
    compiled = make_compiled(
        [
            _contract("C1", access_type="PC", nature_of_activity="Live"),
            _contract("C2", access_type="PC", nature_of_activity="Live"),
        ],
        [
            _access(
                activity_id="A1",
                contract_number="C1",
                start_location_id="SEC:ALP:H01_H02:EB",
                end_location_id="SEC:ALP:H01_H02:EB",
            ),
            _access(
                activity_id="A2",
                contract_number="C2",
                start_location_id="SEC:BET:H01_H02:WB",
                end_location_id="SEC:BET:H01_H02:WB",
            ),
        ],
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1").isdisjoint(_physical_nights(result, "A2"))
    assert reasons.INTERCHANGE in result.binding_reasons["A1"]
    assert reasons.INTERCHANGE in result.binding_reasons["A2"]


def test_compatible_contracts_share_one_physical_night_and_possession():
    compiled = make_compiled(
        [
            _contract("C1", access_type="PC"),
            _contract("C2", access_type="C"),
        ],
        [
            _access(activity_id="A1", contract_number="C1"),
            _access(activity_id="A2", contract_number="C2"),
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1") == _physical_nights(result, "A2")
    assert location_positions(result)[(SECTOR, 1)] == 1
    assert {row.co_share_group for row in result.occupancy} == {"b1"}
    assert reasons.CO_SHARE_PACKED in result.binding_reasons["A1"]
    assert reasons.POSSESSION_MIX in result.binding_reasons["A1"]


def test_co_share_compatible_pair_is_exempt_from_closure_separation():
    """PC+C share a physical night even when their Live closures intersect."""

    compiled = make_compiled(
        [
            _contract("C1", access_type="PC", nature_of_activity="Live"),
            _contract("C2", access_type="C", nature_of_activity="Live"),
        ],
        [
            _access(activity_id="A1", contract_number="C1"),
            _access(activity_id="A2", contract_number="C2"),
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1") == _physical_nights(result, "A2")
    assert reasons.CO_SHARE_PACKED in result.binding_reasons["A1"]


def test_pm_never_shares_a_physical_night_with_a_coworker():
    compiled = make_compiled(
        [
            _contract("C1", access_type="PM"),
            _contract("C2", access_type="C"),
        ],
        [
            _access(activity_id="A1", contract_number="C1"),
            _access(activity_id="A2", contract_number="C2"),
        ],
        capacities={SECTOR: 1},
        horizon_weeks=2,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1").isdisjoint(_physical_nights(result, "A2"))
    assert location_positions(result)[(SECTOR, 1)] == 1
    assert location_positions(result)[(SECTOR, 2)] == 1


def test_four_compatible_contracts_share_one_possession_slot():
    """Supply 1 forces four compatible C contracts into one physical slot."""

    compiled = make_compiled(
        [_contract(f"C{index}") for index in range(1, 5)],
        [
            _access(activity_id=f"A{index}", contract_number=f"C{index}")
            for index in range(1, 5)
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert location_positions(result)[(SECTOR, 1)] == 1
    assert result.objective_breakdown["excess_access_nights_total"] == 0
    assert {row.co_share_group for row in result.occupancy} == {"b1"}


def test_local_access_night_is_ranked_within_each_contract():
    """A contract using physical nights 2 and 4 publishes local nights 1 and 2."""

    compiled = make_compiled(
        [
            _contract(
                "C1",
                access_type="C",
                number_of_maximum_access_per_week=2,
                number_of_workfronts=1,
            )
        ],
        [
            _access(activity_id="A1", contract_number="C1", total_accesses=1),
            _access(activity_id="A2", contract_number="C1", total_accesses=1),
        ],
        capacities={SECTOR: 4},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert {row.access_night for row in result.access} == {1, 2}
    # Distinct physical nights, so two separate possession slots.
    assert len({row.physical_night for row in result.access}) == 2
    assert location_positions(result)[(SECTOR, 1)] == 2


def test_two_pcs_plus_c_use_two_slots_and_one_legal_mix():
    """Two PCs cannot share a slot; the C must join one of them at supply 2."""

    compiled = make_compiled(
        [
            _contract("C1", access_type="PC"),
            _contract("C2", access_type="PC"),
            _contract("C3", access_type="C"),
        ],
        [
            _access(activity_id="P1", contract_number="C1"),
            _access(activity_id="P2", contract_number="C2"),
            _access(activity_id="K1", contract_number="C3"),
        ],
        capacities={SECTOR: 2},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert location_positions(result)[(SECTOR, 1)] == 2
    pc_nights = {
        row.physical_night for row in result.access if row.activity_id in {"P1", "P2"}
    }
    assert len(pc_nights) == 2
    c_night = next(
        row.physical_night for row in result.access if row.activity_id == "K1"
    )
    assert c_night in pc_nights

    groups: dict[str, set[str]] = {}
    for row in result.occupancy:
        if row.location_id == SECTOR:
            groups.setdefault(row.co_share_group, set()).add(row.activity_id)
    members = {frozenset(group) for group in groups.values()}
    assert members == {frozenset({"P1", "K1"}), frozenset({"P2"})} or members == {
        frozenset({"P1"}),
        frozenset({"P2", "K1"}),
    }


def test_compatible_pair_with_disjoint_routes_cannot_co_share():
    """C+C with only a buffered closure interaction must stay on separate nights."""

    compiled = make_compiled(
        [
            _contract("C1", access_type="C", nature_of_activity="Non-live (Consist)"),
            _contract("C2", access_type="C", nature_of_activity="Non-live (Consist)"),
        ],
        [
            _access(activity_id="A1", contract_number="C1"),
            _access(
                activity_id="A2",
                contract_number="C2",
                start_location_id=NEXT_SECTOR,
                end_location_id=NEXT_SECTOR,
            ),
        ],
        capacities={SECTOR: 4, NEXT_SECTOR: 4},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert _physical_nights(result, "A1").isdisjoint(_physical_nights(result, "A2"))
    assert reasons.BUFFER_CLOSURE in result.binding_reasons["A1"]
    assert reasons.BUFFER_CLOSURE in result.binding_reasons["A2"]


def test_closure_reason_codes_are_stable_and_known():
    assert reasons.BUFFER_CLOSURE == "BUFFER_CLOSURE"
    assert reasons.LIVE_MIRROR == "LIVE_MIRROR"
    assert reasons.INTERCHANGE == "INTERCHANGE"
    assert reasons.CLOSURE_RULE_CODES["mirror"] == reasons.LIVE_MIRROR
    assert reasons.POSSESSION_MIX in reasons.ALL_REASON_CODES
    assert reasons.CAPACITY in reasons.ALL_REASON_CODES


def test_access_seq_follows_week_then_local_night_order():
    compiled = make_compiled(
        [
            _contract(
                "C1",
                access_type="C",
                number_of_maximum_access_per_week=2,
                number_of_workfronts=1,
            )
        ],
        [_access(activity_id="A1", contract_number="C1", total_accesses=2)],
        horizon_weeks=12,
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    rows = sorted(result.access, key=lambda row: row.access_seq)
    assert [row.access_seq for row in rows] == list(range(1, len(rows) + 1))
    order = [(row.week, row.access_night) for row in rows]
    assert order == sorted(order)
    assert all(1 <= row.access_night <= 3 for row in rows)


def test_planned_start_and_workload_survive_the_physical_model():
    compiled = make_compiled(
        [_contract("C1")],
        [
            _access(
                activity_id="A1",
                contract_number="C1",
                total_accesses=3,
                planned_start_date=HORIZON_START + timedelta(days=14),
            )
        ],
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    accesses = activity_access(result, "A1")
    assert result.feasible
    assert len(accesses) == 3
    assert min(week for week, _, _ in accesses) >= 3
    assert sum(3 if eclo else 2 for _, _, eclo in accesses) >= 6
