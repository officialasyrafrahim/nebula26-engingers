"""Fragility and what-if sandbox (F-BONUS-002).

The tests build tiny synthetic compiled instances directly and only exercise
CP-SAT when the native runtime is importable, mirroring the rest of the solver
suite. They pin four promises:

* a supply cut that overruns hard capacity is reported infeasible, and the
  bounded search names the breaking supply and the smallest reduction;
* a supply cut a legal co-share can absorb stays feasible;
* a variant the physical witness rejects is reported UNSAFE with no schedule;
* the sandbox is deterministic for a fixed seed and never rewrites the source
  job's published schedule rows.
"""

from __future__ import annotations

import pytest

from app.modules.runs import service
from app.modules.solver import cp_sat_available, sandbox
from app.modules.validator.witness import PhysicalCheck, PhysicalWitnessReport
from app.workers import rail_solver_worker
from tests.conftest import MINIMAL_INSTANCE_FILES
from tests.test_rail_solver import make_compiled

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"


def _sector_activity(activity_id: str, contract: str, accesses: int = 1) -> dict:
    return {
        "activity_id": activity_id,
        "contract_number": contract,
        "start_location_id": SECTOR,
        "end_location_id": SECTOR,
        "total_accesses": accesses,
    }


def _pm_c_compiled(capacity: int = 2, weeks: int = 1):
    return make_compiled(
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
        [_sector_activity("A1", "C1"), _sector_activity("A2", "C2")],
        capacities={SECTOR: capacity},
        horizon_weeks=weeks,
    )


def _co_share_compiled(capacity: int = 2, weeks: int = 1):
    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_workfronts": 2,
                "number_of_maximum_access_per_week": 2,
            }
        ],
        [_sector_activity("A1", "C1"), _sector_activity("A2", "C1")],
        capacities={SECTOR: capacity},
        horizon_weeks=weeks,
    )


def test_fragility_names_the_smallest_breaking_supply_reduction():
    compiled = _pm_c_compiled(capacity=2, weeks=1)

    signal = sandbox.fragility_supply(
        compiled,
        "A",
        SECTOR,
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
        max_trials=8,
    )

    assert signal.base_supply == 2
    assert signal.bounded is True
    assert signal.feasible_floor == 2
    assert signal.breaking_new_supply == 1
    assert signal.smallest_supply_reduction == 1
    assert signal.trials <= 8
    assert SECTOR in signal.note


def test_what_if_supply_cut_absorbed_by_legal_co_share_stays_feasible():
    compiled = _co_share_compiled(capacity=2, weeks=1)

    outcome = sandbox.evaluate_what_if(
        compiled,
        "A",
        sandbox.WhatIfKnobs(supply={SECTOR: 1}),
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )

    assert outcome.feasible is True
    assert outcome.safe is True
    assert outcome.witness is not None and outcome.witness.passed
    assert outcome.result.access
    assert outcome.applied["supply"] == {SECTOR: 1}


def test_what_if_workfront_and_eclo_knobs_are_applied():
    compiled = _co_share_compiled(capacity=1, weeks=1)

    blocked = sandbox.evaluate_what_if(
        compiled,
        "A",
        sandbox.WhatIfKnobs(workfronts={"C1": 1}),
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )
    assert blocked.feasible is False
    assert blocked.safe is False
    assert blocked.applied["workfronts"] == {"C1": 1}

    allowed = sandbox.evaluate_what_if(
        compiled,
        "A",
        sandbox.WhatIfKnobs(eclo_allowed=True),
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )
    assert allowed.feasible is True
    assert allowed.applied["eclo_allowed"] is True


def test_sandbox_withholds_a_schedule_the_witness_rejects(monkeypatch):
    compiled = _co_share_compiled(capacity=2, weeks=1)

    def failing_witness(compiled, policy, access_rows, occupancy_rows):
        return PhysicalWitnessReport(
            passed=False,
            checks=[PhysicalCheck(name="forced", passed=False, detail={})],
        )

    monkeypatch.setattr(sandbox, "check_physical_witness", failing_witness)

    outcome = sandbox.evaluate_what_if(
        compiled,
        "A",
        sandbox.WhatIfKnobs(supply={SECTOR: 1}),
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )

    assert outcome.feasible is False
    assert outcome.safe is False
    assert outcome.status == "UNSAFE"
    assert outcome.result.access == ()
    assert outcome.result.occupancy == ()
    assert outcome.notes


def test_what_if_is_deterministic_for_a_fixed_seed():
    compiled = _co_share_compiled(capacity=2, weeks=1)
    knobs = sandbox.WhatIfKnobs(supply={SECTOR: 1})

    first = sandbox.evaluate_what_if(
        compiled, "A", knobs, time_limit_seconds=10, seed=7, horizon_extension_weeks=0
    )
    second = sandbox.evaluate_what_if(
        compiled, "A", knobs, time_limit_seconds=10, seed=7, horizon_extension_weeks=0
    )

    assert [row.model_dump() for row in first.result.access] == [
        row.model_dump() for row in second.result.access
    ]
    assert [row.model_dump() for row in first.result.occupancy] == [
        row.model_dump() for row in second.result.occupancy
    ]
    assert sandbox.metrics_from_result(first.result) == sandbox.metrics_from_result(
        second.result
    )


def test_sandbox_rejects_unknown_location_and_contract():
    compiled = _co_share_compiled(capacity=2, weeks=1)

    with pytest.raises(sandbox.UnknownEntityError):
        sandbox.evaluate_what_if(
            compiled, "A", sandbox.WhatIfKnobs(supply={"NOPE": 1})
        )
    with pytest.raises(sandbox.UnknownEntityError):
        sandbox.evaluate_what_if(
            compiled, "A", sandbox.WhatIfKnobs(workfronts={"NOPE": 1})
        )
    with pytest.raises(sandbox.UnknownEntityError):
        sandbox.fragility_supply(compiled, "A", "NOPE")


def _minimal_files() -> dict[str, bytes]:
    return {
        name: text.encode("utf-8") for name, text in MINIMAL_INSTANCE_FILES.items()
    }


def test_sandbox_api_round_trip_keeps_published_schedule(
    client, worker_session, fake_solver_result, monkeypatch
):
    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)

    run = client.post(
        "/api/v1/runs",
        files=[
            ("files", (name, data, "text/csv"))
            for name, data in _minimal_files().items()
        ],
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    job = client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": "A"})
    assert job.status_code == 202
    job_id = job.json()["id"]
    assert rail_solver_worker.process_next_job() is True

    schedule_before = client.get(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule"
    ).json()

    response = client.post(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/sandbox",
        json={
            "supply": {SECTOR: 4},
            "time_limit_seconds": 5,
            "seed": 42,
            "horizon_extension_weeks": 0,
            "fragility_location_id": SECTOR,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_scenario"] == "A"
    assert body["variant"]["feasible"] is True
    assert body["variant"]["safe"] is True
    assert body["variant"]["access"]
    assert body["fragility"]["location_id"] == SECTOR
    assert body["fragility"]["base_supply"] == 4
    assert body["fragility"]["breaking_new_supply"] == 0
    assert body["fragility"]["smallest_supply_reduction"] == 4
    assert body["delta"]["access_nights_total"] == 0

    schedule_after = client.get(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule"
    ).json()
    assert schedule_after["access"] == schedule_before["access"]
    assert schedule_after["occupancy"] == schedule_before["occupancy"]


def test_sandbox_rejects_a_supply_override_for_an_unknown_location(
    db_session,
):
    from fastapi import HTTPException

    from app.domain.enums import JobState, Scenario
    from app.domain.models import ScenarioJob
    from app.domain.schemas import SandboxRequest

    run = service.create_run(db_session, list(_minimal_files().items()))
    job = ScenarioJob(
        run_id=run.id,
        scenario=Scenario.A,
        state=JobState.COMPLETED,
        result={"objective_breakdown": {}},
    )
    db_session.add(job)
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        service.create_sandbox(
            db_session,
            run.id,
            job.id,
            SandboxRequest(supply={"NOPE": 1}),
        )
    assert excinfo.value.status_code == 422
    assert "unknown location" in str(excinfo.value.detail)
