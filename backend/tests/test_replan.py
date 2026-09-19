"""Dynamic disruption impact assessment and minimal-churn replanning (F-BONUS-001).

The tests build tiny synthetic compiled instances directly and only exercise
CP-SAT when the native runtime is importable, mirroring the rest of the solver
suite. They pin three promises:

* a supply drop replans with a strictly smaller churn diff than a from-scratch
  solve of the disrupted instance;
* a disruption that removes all feasible placements is reported INFEASIBLE and
  emits no schedule;
* the same disruption and seed replan deterministically.

The impact assessment is checked against persisted schedule evidence, and the
API round trip proves a replan never rewrites the source job's published CSVs.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.enums import JobState, Scenario
from app.domain.models import (
    ContractResultRow,
    ScenarioJob,
    ScheduleAccessRow,
    ScheduleOccupancyRow,
)
from app.domain.schemas import (
    LocationUnavailable,
    ReplanRequest,
    SupplyDrop,
    UrgentActivityInjection,
)
from app.modules.runs import service
from app.modules.solver import cp_sat_available, replan, solve
from tests.test_rail_solver import HORIZON_START, make_compiled

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"


def _contracts() -> list[dict]:
    return [
        {
            "contract_number": "C1",
            "access_type": "C",
            "nature_of_activity": "Non-live (Others)",
        }
    ]


def _activities(specs: list[tuple[str, int]]) -> list[dict]:
    return [
        {
            "activity_id": activity_id,
            "contract_number": "C1",
            "start_location_id": SECTOR,
            "end_location_id": SECTOR,
            "total_accesses": 1,
            "planned_start_date": HORIZON_START + timedelta(days=days),
        }
        for activity_id, days in specs
    ]


def _compiled(capacities: dict[str, int], specs: list[tuple[str, int]], weeks: int = 8):
    return make_compiled(
        _contracts(),
        _activities(specs),
        capacities=capacities,
        horizon_weeks=weeks,
    )


def _slots(result):
    return {
        (row.activity_id, row.week): row.physical_night for row in result.access
    }


def test_supply_drop_replan_has_smaller_churn_than_from_scratch():
    compiled = _compiled({SECTOR: 2}, [("A1", 0), ("A2", 0), ("A3", 7)])
    original = solve(compiled, "A", time_limit_seconds=10, seed=42, horizon_extension_weeks=0)
    assert original.feasible
    reference = replan.build_reference(original.access)
    assert reference.access_count == 3

    drop = SupplyDrop(location_id=SECTOR, new_supply=1)
    outcome = replan.solve_replan(
        compiled,
        "A",
        [drop],
        reference,
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )
    assert outcome.result.feasible
    assert outcome.safe
    churn_diff = replan.diff_against(
        original.access, outcome.result, required_activities=compiled.activities
    )

    disrupted, _effects = replan.resolve_disruptions(compiled, [drop])
    scratch = solve(
        disrupted, "A", time_limit_seconds=10, seed=42, horizon_extension_weeks=0
    )
    assert scratch.feasible
    scratch_diff = replan.diff_against(
        original.access, scratch, required_activities=compiled.activities
    )

    assert churn_diff["totals"]["moved_accesses"] < scratch_diff["totals"]["moved_accesses"]
    assert outcome.churn_moved == churn_diff["totals"]["moved_accesses"]
    assert outcome.churn_moved >= 1


def test_infeasible_disruption_is_reported_infeasible_without_a_schedule():
    compiled = _compiled({SECTOR: 2}, [("A1", 0)])
    original = solve(compiled, "B", time_limit_seconds=10, seed=42, horizon_extension_weeks=0)
    assert original.feasible
    reference = replan.build_reference(original.access)

    unavailable = LocationUnavailable(location_id=SECTOR)
    outcome = replan.solve_replan(
        compiled,
        "B",
        [unavailable],
        reference,
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )

    assert outcome.result.feasible is False
    assert outcome.result.status == "INFEASIBLE"
    assert outcome.safe is False
    assert outcome.result.access == ()
    assert outcome.result.occupancy == ()
    assert outcome.result.infeasibility_reasons

    diff = replan.diff_against(
        original.access, outcome.result, required_activities=compiled.activities
    )
    assert diff["newly_unsatisfiable"] == ["A1"]


def test_replan_is_deterministic_for_a_fixed_seed():
    compiled = _compiled({SECTOR: 2}, [("A1", 0), ("A2", 0), ("A3", 7)])
    original = solve(compiled, "A", time_limit_seconds=10, seed=7, horizon_extension_weeks=0)
    reference = replan.build_reference(original.access)
    drop = SupplyDrop(location_id=SECTOR, new_supply=1)

    first = replan.solve_replan(
        compiled,
        "A",
        [drop],
        reference,
        time_limit_seconds=10,
        seed=7,
        horizon_extension_weeks=0,
    )
    second = replan.solve_replan(
        compiled,
        "A",
        [drop],
        reference,
        time_limit_seconds=10,
        seed=7,
        horizon_extension_weeks=0,
    )

    assert first.result.access == second.result.access
    assert first.result.occupancy == second.result.occupancy
    assert first.churn_moved == second.churn_moved


def test_impact_assessment_names_invalid_placements_and_workload_change():
    compiled = _compiled({SECTOR: 2}, [("A1", 0), ("A2", 0), ("A3", 7)])
    original = solve(compiled, "A", time_limit_seconds=10, seed=42, horizon_extension_weeks=0)
    assert original.feasible

    drop = SupplyDrop(location_id=SECTOR, new_supply=1)
    impact = replan.assess_impact(
        compiled,
        [drop],
        original.access,
        original.occupancy,
        original.contract_results,
    )

    assert impact["affected_activities"] == ["A2"]
    assert impact["affected_contracts"] == ["C1"]
    assert [entry["excess"] for entry in impact["affected_location_weeks"]] == [1]
    assert impact["invalid_placements"][0]["reason"] == "supply_drop"
    assert impact["workload"] == {
        "access_nights_before": 3,
        "invalid_access_nights": 1,
        "injected_access_nights": 0,
        "access_nights_after_lower_bound": 2,
    }
    assert impact["overrun"]["worst_case_additional_overrun_days"] == 7


def test_urgent_activity_injection_adds_workload_and_is_placed():
    compiled = _compiled({SECTOR: 4}, [("A1", 0)])
    original = solve(compiled, "A", time_limit_seconds=10, seed=42, horizon_extension_weeks=0)
    reference = replan.build_reference(original.access)

    urgent = UrgentActivityInjection(
        activity_id="U1",
        contract_number="C1",
        start_location_id=SECTOR,
        end_location_id=SECTOR,
        total_accesses=1,
        planned_start_date=HORIZON_START,
        activity_priority=1,
    )
    impact = replan.assess_impact(
        compiled, [urgent], original.access, original.occupancy, original.contract_results
    )
    assert impact["workload"]["injected_access_nights"] == 1
    assert "U1" in impact["affected_activities"]
    assert "C1" in impact["affected_contracts"]

    outcome = replan.solve_replan(
        compiled,
        "A",
        [urgent],
        reference,
        time_limit_seconds=10,
        seed=42,
        horizon_extension_weeks=0,
    )
    assert outcome.result.feasible
    assert outcome.safe
    assert "U1" in {row.activity_id for row in outcome.result.access}
    diff = replan.diff_against(
        original.access,
        outcome.result,
        required_activities=[*compiled.activities, "U1"],
    )
    assert diff["added"] == ["U1"]


def test_replan_api_round_trip_keeps_published_csvs(client, worker_session):
    from app.modules.export import archive_members
    from app.workers import rail_solver_worker

    uploads = {
        name: data.decode("utf-8")
        for name, data in _minimal_files().items()
    }
    run = client.post(
        "/api/v1/runs",
        files=[("files", (name, text, "text/csv")) for name, text in uploads.items()],
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    job = client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": "A"})
    assert job.status_code == 202
    job_id = job.json()["id"]

    assert rail_solver_worker.process_next_job() is True
    schedule_before = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule")
    export_before = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/export")
    assert schedule_before.status_code == 200
    assert export_before.status_code == 200

    response = client.post(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/replan",
        json={
            "disruptions": [
                {"kind": "supply_drop", "location_id": SECTOR, "new_supply": 1}
            ],
            "time_limit_seconds": 5,
            "seed": 42,
            "horizon_extension_weeks": 0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE")
    assert body["safe"] is True
    assert body["result"]["access"]
    assert body["diff"]["totals"]["moved_accesses"] == 0
    assert body["churn_cost"] == 0
    assert body["impact"]["affected_activities"] == []

    fetched = client.get(f"/api/v1/runs/{run_id}/replans/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]

    schedule_after = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule")
    export_after = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/export")
    assert schedule_after.json() == schedule_before.json()
    assert set(archive_members(export_after.content)) == set(
        archive_members(export_before.content)
    )
    assert export_after.content == export_before.content


def test_replan_api_reports_infeasible_for_a_hard_removal(client, db_session):
    run = service.create_run(db_session, list(_minimal_files().items()))
    source = ScenarioJob(
        run_id=run.id,
        scenario=Scenario.B,
        state=JobState.COMPLETED,
        result={"status": "OPTIMAL"},
    )
    db_session.add(source)
    db_session.commit()
    db_session.add_all(
        [
            ScheduleAccessRow(
                job_id=source.id,
                activity_id="A1",
                access_seq=1,
                week=1,
                eclo=False,
                access_night=1,
                physical_night=1,
            ),
            ScheduleOccupancyRow(
                job_id=source.id,
                activity_id="A1",
                week=1,
                location_id=SECTOR,
                co_share_group="b1",
            ),
            ContractResultRow(
                job_id=source.id,
                contract_number="C1",
                simulated_completion_date=HORIZON_START,
                overrun_days=0,
            ),
        ]
    )
    db_session.commit()

    row = service.create_replan(
        db_session,
        run.id,
        source.id,
        ReplanRequest(
            disruptions=[LocationUnavailable(location_id=SECTOR)],
            time_limit_seconds=5,
            seed=42,
            horizon_extension_weeks=0,
        ),
    )

    assert row.status == "INFEASIBLE"
    assert row.safe is False
    assert row.result is not None
    assert row.result["feasible"] is False
    assert row.diff["newly_unsatisfiable"] == ["A1"]


def _minimal_files() -> dict[str, bytes]:
    from tests.conftest import MINIMAL_INSTANCE_FILES

    return {
        name: text.encode("utf-8") for name, text in MINIMAL_INSTANCE_FILES.items()
    }
