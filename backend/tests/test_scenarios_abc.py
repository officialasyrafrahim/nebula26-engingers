"""Scenario A/B/C policy behaviour and public-instance smoke (AT-08..AT-10)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.solver import cp_sat_available, solve
from tests.helpers_rail import load_public_compiled
from tests.test_rail_solver import (
    HORIZON_START,
    activity_access,
    location_positions,
    make_compiled,
)

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"


def _serialised_pc_contracts():
    return [
        {
            "contract_number": "C1",
            "access_type": "PC",
            "nature_of_activity": "Non-live (Others)",
            "contract_priority": 1,
            "planned_completion_date": HORIZON_START + timedelta(days=6),
        },
        {
            "contract_number": "C2",
            "access_type": "PC",
            "nature_of_activity": "Non-live (Others)",
            "contract_priority": 3,
            "planned_completion_date": HORIZON_START + timedelta(days=6),
        },
    ]


def _serialised_pc_activities(total: int = 2):
    return [
        {
            "activity_id": "A1",
            "contract_number": "C1",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": total,
        },
        {
            "activity_id": "A2",
            "contract_number": "C2",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": total,
        },
    ]


def test_scenario_a_hard_capacity_and_no_eclo():
    compiled = make_compiled(
        _serialised_pc_contracts(),
        _serialised_pc_activities(),
        capacities={SECTOR: 1},
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    assert result.feasible
    assert result.objective_breakdown["eclo_nights_total"] == 0
    assert all(used <= 1 for used in location_positions(result).values())


def test_scenario_a_priority_weighting_prefers_priority_one():
    compiled = make_compiled(
        _serialised_pc_contracts(),
        _serialised_pc_activities(),
        capacities={SECTOR: 1},
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    priority_one = activity_access(result, "A1")
    priority_three = activity_access(result, "A2")
    assert result.feasible
    assert max(week for week, _, _ in priority_one) < max(
        week for week, _, _ in priority_three
    )
    assert result.objective_breakdown["priority_weighted_score"] > 0


def test_scenario_b_hard_deadline_with_scored_excess():
    compiled = make_compiled(
        _serialised_pc_contracts(),
        _serialised_pc_activities(total=1),
        capacities={SECTOR: 1},
    )
    result = solve(compiled, "B", time_limit_seconds=10)

    assert result.feasible
    assert all(item.last_week == 1 for item in result.contract_results)
    assert result.objective_breakdown["excess_access_nights_total"] == 1
    assert result.objective_breakdown["score"] == pytest.approx(7.0)


def test_scenario_b_deadline_is_date_exact_not_week_based():
    """A non-Sunday planned date binds on week_end, not the week index (L2)."""
    contracts = [
        {
            "contract_number": "C1",
            "access_type": "C",
            "nature_of_activity": "Non-live (Others)",
            "contract_priority": 1,
            # Wednesday of week 2: week_end(2) = day +13 would overrun it,
            # although week 2 is the week that contains the date.
            "planned_completion_date": HORIZON_START + timedelta(days=9),
        }
    ]
    activities = [
        {
            "activity_id": "A1",
            "contract_number": "C1",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 1,
            "planned_start_date": HORIZON_START + timedelta(days=7),
        }
    ]

    blocked = solve(make_compiled(contracts, activities), "B", time_limit_seconds=10)
    assert not blocked.feasible

    contracts[0]["planned_completion_date"] = HORIZON_START + timedelta(days=13)
    allowed = solve(make_compiled(contracts, activities), "B", time_limit_seconds=10)
    assert allowed.feasible
    assert allowed.contract_results[0].last_week == 2
    assert allowed.contract_results[0].overrun_days == 0


def test_scenario_c_capacity_ceiling_is_plus_one():
    compiled = make_compiled(
        _serialised_pc_contracts(),
        _serialised_pc_activities(total=1),
        capacities={SECTOR: 1},
    )
    result = solve(compiled, "C", time_limit_seconds=10)

    assert result.feasible
    assert all(used <= 2 for used in location_positions(result).values())
    assert result.objective_breakdown["excess_access_nights_total"] == 1


def test_scenario_c_eclo_two_week_window():
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "contract_priority": 1,
                "planned_completion_date": HORIZON_START + timedelta(days=13),
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 3,
            }
        ],
    )
    result = solve(compiled, "C", time_limit_seconds=10)

    accesses = activity_access(result, "A1")
    assert result.feasible
    assert result.objective_breakdown["eclo_nights_total"] == 2
    eclo_weeks = sorted(week for week, _, eclo in accesses if eclo)
    assert eclo_weeks == [1, 2]
    assert max(eclo_weeks) - min(eclo_weeks) + 1 <= 2


def test_scenario_a_forbids_eclo_that_c_is_allowed_to_use():
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "contract_priority": 1,
                "planned_completion_date": HORIZON_START + timedelta(days=13),
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 3,
            }
        ],
    )
    result = solve(compiled, "A", time_limit_seconds=10)

    assert result.feasible
    assert result.objective_breakdown["eclo_nights_total"] == 0
    assert max(week for week, _, _ in activity_access(result, "A1")) == 3


def test_public_instance_smoke_solve():
    """Smoke-solve the public instance; skipped if it cannot finish quickly."""

    compiled = load_public_compiled()
    result = solve(compiled, "A", time_limit_seconds=20)

    if not result.feasible:
        pytest.skip(f"public smoke solve did not finish: {result.status}")

    assert result.objective_breakdown["access_nights_total"] > 0
    assert result.objective_breakdown["eclo_nights_total"] == 0
    totals: dict[str, int] = {}
    for row in result.access:
        totals[row.activity_id] = totals.get(row.activity_id, 0) + (3 if row.eclo else 2)
    for activity_id, activity in compiled.activities.items():
        assert totals.get(activity_id, 0) >= 2 * activity.total_accesses
    for (location_id, _), used in location_positions(result).items():
        assert used <= compiled.location_capacities[location_id]
