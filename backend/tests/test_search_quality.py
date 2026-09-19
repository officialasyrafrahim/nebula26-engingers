"""Search quality settings: worker portfolio and score-first objective scaling."""

from __future__ import annotations

import pytest

from app.modules.solver import cp_sat_available
from app.modules.solver.engine import search_workers
from app.modules.solver.objectives import OVERSHOOT_WEIGHT
from tests.test_rail_solver import make_compiled


def test_search_workers_defaults_to_one(monkeypatch):
    monkeypatch.delenv("RAO_SEARCH_WORKERS", raising=False)
    assert search_workers() == 1


def test_search_workers_honours_env(monkeypatch):
    monkeypatch.setenv("RAO_SEARCH_WORKERS", "8")
    assert search_workers() == 8


@pytest.mark.parametrize("value", ["0", "-1", "65", "four"])
def test_search_workers_rejects_invalid(monkeypatch, value):
    monkeypatch.setenv("RAO_SEARCH_WORKERS", value)
    with pytest.raises(ValueError):
        search_workers()


def _scored_instance():
    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:EB",
                "end_location_id": "SEC:ALP:S01_S02:EB",
                "total_accesses": 2,
            }
        ],
        horizon_weeks=3,
    )


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
@pytest.mark.parametrize("scenario", ["A", "B", "C"])
def test_objective_scales_scored_terms_past_overshoot(scenario):
    """The score multiplier must exceed the whole overshoot domain.

    A direct end-to-end solve on a tiny instance does not expose the difference
    in practice, so the reviewed guarantee is checked on the built objective
    expression itself: every scored coefficient is scaled by at least
    ``overshoot_bound + 1`` while the overshoot coefficient stays at one.
    """

    from app.modules.compiler.policy import get_policy
    from app.modules.solver.model import load_cp_model
    from app.modules.solver.objectives import build_objective
    from app.modules.solver.variables import build_variables

    compiled = _scored_instance()
    policy = get_policy(scenario)
    cp = load_cp_model()
    model = cp.CpModel()
    variables = build_variables(model, compiled, policy, 3)
    build_objective(model, compiled, variables, policy)

    proto = model.Proto()
    names = {index: variable.name for index, variable in enumerate(proto.variables)}
    coefficients = {
        names[index]: coefficient
        for index, coefficient in zip(
            proto.objective.vars, proto.objective.coeffs, strict=True
        )
    }
    overshoot_bound = sum(3 * len(weeks) for weeks in variables.activity_weeks.values())
    multiplier = overshoot_bound + 1
    assert multiplier > 1

    assert coefficients["overshoot"] == OVERSHOOT_WEIGHT
    assert any(name != "overshoot" for name in coefficients)
    for name, coefficient in coefficients.items():
        if name == "overshoot":
            continue
        assert coefficient % multiplier == 0
        assert abs(coefficient) >= multiplier
