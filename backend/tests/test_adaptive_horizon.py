"""Adaptive horizon growth for congestion-safe completion (F-SOLVER-008).

The solver starts at the configured horizon (nominal weeks plus the extension)
and grows it inside the overall time budget when a complete workload does not
fit. Congestion must therefore not be reported as proven infeasibility merely
because the initial extension was exhausted. A hard scenario deadline that
cannot be met still reports infeasible.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.solver import cp_sat_available, solve
from tests.test_rail_solver import HORIZON_START, make_compiled

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"


def _pm_contract():
    return [
        {
            "contract_number": "C1",
            "access_type": "PM",
            "nature_of_activity": "Non-live (Others)",
        }
    ]


def _pm_activities(count: int):
    return [
        {
            "activity_id": f"A{index}",
            "contract_number": "C1",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 1,
        }
        for index in range(1, count + 1)
    ]


def test_initial_extension_is_not_a_hard_stop():
    """Three PM accesses at supply 1 need three weeks; initial extension gives two."""

    compiled = make_compiled(
        _pm_contract(),
        _pm_activities(3),
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=1)

    assert result.feasible
    assert result.horizon_weeks_used >= 3
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_congestion_is_not_reported_as_proven_infeasibility():
    compiled = make_compiled(
        _pm_contract(),
        _pm_activities(3),
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=1)

    assert result.feasible
    assert result.status != "INFEASIBLE"
    assert result.infeasibility_reasons == ()


def test_zero_extension_disables_adaptive_growth():
    """An explicitly zero extension keeps the fixed-horizon contract."""

    compiled = make_compiled(
        _pm_contract(),
        _pm_activities(3),
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible is False
    assert result.infeasibility_reasons


def test_growth_returns_a_complete_incumbent():
    compiled = make_compiled(
        _pm_contract(),
        _pm_activities(4),
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=1)

    assert result.feasible
    totals: dict[str, int] = {}
    for row in result.access:
        totals[row.activity_id] = totals.get(row.activity_id, 0) + (3 if row.eclo else 2)
    for activity_id in ("A1", "A2", "A3", "A4"):
        assert totals.get(activity_id, 0) >= 2


def test_growth_is_deterministic_for_a_fixed_seed():
    compiled = make_compiled(
        _pm_contract(),
        _pm_activities(3),
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    first = solve(compiled, "A", time_limit_seconds=10, seed=7, horizon_extension_weeks=1)
    second = solve(compiled, "A", time_limit_seconds=10, seed=7, horizon_extension_weeks=1)

    assert first.feasible and second.feasible
    assert first.access == second.access
    assert first.occupancy == second.occupancy
    assert first.horizon_weeks_used == second.horizon_weeks_used


def test_hard_deadline_infeasibility_still_reports_infeasible():
    """Growth must not mask a Scenario B deadline that cannot be met."""

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
    )
    result = solve(compiled, "B", time_limit_seconds=10, horizon_extension_weeks=3)

    assert result.feasible is False
    assert result.infeasibility_reasons
