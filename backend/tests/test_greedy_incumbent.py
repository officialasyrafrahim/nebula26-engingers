"""Greedy incumbent builder and witness-gate regressions (F-SOLVER-009).

Under a tight budget CP-SAT can time out with no incumbent. The greedy pass
builds a complete physical schedule, the independent witness gates it, and only
a witness-passing schedule is used as a hint or published when the search runs
out of budget. These tests pin both the rescue path and the safety guardrails.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.compiler.policy import get_policy
from app.modules.solver import cp_sat_available, engine, solve
from app.modules.solver.greedy import (
    GreedyPlacement,
    GreedySolution,
    build_greedy_solution,
)
from app.modules.solver.variables import build_variables
from app.modules.validator.witness import check_physical_witness
from tests.test_rail_solver import HORIZON_START, make_compiled

requires_cp_sat = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"
DISJOINT_SECTOR = "SEC:ALP:H01_H02:EB"


def _pm_contract() -> list[dict]:
    return [
        {
            "contract_number": "C1",
            "access_type": "PM",
            "nature_of_activity": "Non-live (Others)",
            "number_of_maximum_access_per_week": 7,
            "number_of_workfronts": 7,
        }
    ]


def _pm_activities(count: int) -> list[dict]:
    return [
        {
            "activity_id": f"A{index:03d}",
            "contract_number": "C1",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 1,
        }
        for index in range(1, count + 1)
    ]


def _conflicting_pc_compiled():
    """Two PC contracts whose buffer closures overlap but cannot co-share."""

    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Consist)",
            },
            {
                "contract_number": "C2",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Consist)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": DISJOINT_SECTOR,
                "end_location_id": DISJOINT_SECTOR,
                "total_accesses": 1,
            },
        ],
        horizon_weeks=1,
    )


def _variables(compiled, policy, total_weeks):
    cp = engine.load_cp_model()
    return build_variables(cp.CpModel(), compiled, policy, total_weeks)


def _greedy_witness_passes(compiled, policy, total_weeks, greedy) -> bool:
    variables = _variables(compiled, policy, total_weeks)
    access_rows, occupancy_rows = engine._greedy_hint_rows(
        compiled, variables, greedy
    )
    return check_physical_witness(
        compiled, policy, access_rows, occupancy_rows
    ).passed


@requires_cp_sat
def test_congested_budget_returns_witness_passing_greedy_incumbent(monkeypatch):
    """A tight budget returns the gated greedy schedule instead of UNKNOWN."""

    compiled = make_compiled(
        _pm_contract(),
        _pm_activities(60),
        capacities={SECTOR: 3},
        horizon_weeks=20,
    )
    policy = get_policy("A")
    total_weeks = 20

    greedy = build_greedy_solution(compiled, policy, total_weeks)
    assert greedy is not None
    assert _greedy_witness_passes(compiled, policy, total_weeks, greedy)

    result = solve(
        compiled, "A", time_limit_seconds=0.1, horizon_extension_weeks=0
    )
    assert result.feasible
    assert result.status == "FEASIBLE"
    report = check_physical_witness(
        compiled, policy, result.access, result.occupancy
    )
    assert report.passed, report.checks

    # Without the greedy path the same tight budget has no incumbent, so the
    # rescue above comes from the gated greedy schedule rather than luck.
    monkeypatch.setattr(engine, "_witness_checked_greedy", lambda *args, **kwargs: None)
    unfinished = solve(
        compiled, "A", time_limit_seconds=0.1, horizon_extension_weeks=0
    )
    assert unfinished.feasible is False


def test_greedy_builder_rejects_a_layout_it_cannot_place_safely():
    """PM plus C at supply one cannot share a week; the builder returns None."""

    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )

    assert build_greedy_solution(compiled, get_policy("A"), 1) is None


@requires_cp_sat
def test_overconstrained_instance_never_emits_an_unsafe_schedule():
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )

    result = solve(compiled, "A", time_limit_seconds=0.1, horizon_extension_weeks=0)

    assert result.feasible is False
    assert result.access == ()
    assert result.occupancy == ()


@requires_cp_sat
def test_witness_gate_rejects_an_injected_unsafe_hint(monkeypatch):
    """A physical-night conflict injected as a hint is discarded, not trusted."""

    compiled = _conflicting_pc_compiled()
    policy = get_policy("A")
    unsafe = GreedySolution(
        placements=(
            GreedyPlacement(activity_id="A1", week=1, physical_night=1, eclo=False),
            GreedyPlacement(activity_id="A2", week=1, physical_night=1, eclo=False),
        )
    )
    monkeypatch.setattr(engine, "build_greedy_solution", lambda *args, **kwargs: unsafe)

    variables = _variables(compiled, policy, 1)
    assert engine._witness_checked_greedy(compiled, policy, variables, 1) is None


@requires_cp_sat
def test_provably_infeasible_scenario_b_stays_infeasible():
    """The greedy deadline guard must not mask a proven Scenario B infeasibility."""

    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "planned_completion_date": HORIZON_START + timedelta(days=6),
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
                "planned_start_date": HORIZON_START + timedelta(days=14),
            }
        ],
        horizon_weeks=4,
    )

    assert build_greedy_solution(compiled, get_policy("B"), 4) is None

    result = solve(compiled, "B", time_limit_seconds=0.5, horizon_extension_weeks=3)

    assert result.feasible is False
    assert result.status == "INFEASIBLE"
    assert result.infeasibility_reasons
    assert result.access == ()
