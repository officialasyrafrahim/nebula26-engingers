"""Scenario C dominance over Scenario A.

Scenario C relaxes Scenario A (ECLO allowed, one extra capacity unit per
location-week), so any A-feasible schedule is C-feasible and C's optimum can
never be worse than A's. These tests pin that invariant and the seeding that
enforces it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.solver import cp_sat_available, solve
from app.modules.solver.results import AccessPlacement, SolverResult
from tests.test_rail_solver import HORIZON_START, make_compiled

SECTOR = "SEC:ALP:S01_S02:EB"


def _congested_instance():
    """One long activity whose contract date is already in the past."""

    planned_completion = HORIZON_START + timedelta(days=6)
    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "contract_priority": 3,
                "planned_completion_date": planned_completion,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 4,
                "activity_priority": 1,
            }
        ],
        capacities={SECTOR: 1},
        horizon_weeks=6,
    )


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_scenario_c_never_scores_worse_than_scenario_a():
    compiled = _congested_instance()

    a_result = solve(compiled, "A", time_limit_seconds=10, seed=42)
    c_result = solve(compiled, "C", time_limit_seconds=10, seed=42)

    assert a_result.feasible
    assert c_result.feasible
    assert (
        c_result.objective_breakdown["score"]
        <= a_result.objective_breakdown["score"] + 1e-6
    )


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_scenario_c_seeds_from_scenario_a():
    compiled = _congested_instance()

    c_result = solve(compiled, "C", time_limit_seconds=10, seed=42)

    assert c_result.feasible
    assert c_result.objective_breakdown["incumbent_source"] == "scenario_a"
    assert c_result.objective_breakdown["best_bound"] is not None


def test_incumbent_from_result_projects_access_rows():
    from app.modules.solver.engine import _incumbent_from_result

    result = SolverResult(
        feasible=True,
        scenario="A",
        status="FEASIBLE",
        horizon_weeks_used=1,
        access=(
            AccessPlacement(
                activity_id="A1",
                access_seq=1,
                week=1,
                eclo=False,
                access_night=1,
                physical_night=3,
            ),
        ),
        objective_breakdown={"priority_weighted_score": 16.8},
    )

    incumbent = _incumbent_from_result(result, source="scenario_a")

    assert incumbent is not None
    assert incumbent.assignment == {("A1", 1, 3, 0): 1}
    assert incumbent.score_bound == 16.8
    assert incumbent.source == "scenario_a"
