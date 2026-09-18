"""Mandatory planning constraints, objectives and alternative-plan tests.

ERD requirements: PLN-01, PLN-02, PLN-03; acceptance tests: AT-06, AT-07.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.domain.enums import InterventionPriority, JobState, WorkPackageState
from app.domain.models import Crew, PlanJob, ScheduleAssignment, ScheduleProposal
from app.modules.planning import solver as solver_module
from app.modules.planning.solver import PlanRequest, solve_alternatives, solve_plan
from app.workers import solver_worker
from tests.helpers_planning import plan_payload, reset_queue, seed_scenario

BASE = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def worker_session(db_session, monkeypatch):
    """Bind the asynchronous worker to the test database session."""
    monkeypatch.setattr(solver_worker, "SessionLocal", lambda: db_session)
    return db_session


def _work_package(
    identifier: str,
    *,
    priority: str = "HIGH",
    asset_id: str | None = None,
    duration: int = 60,
    competency: str | None = "mechanical",
    parts: list | None = None,
    tools: list | None = None,
) -> dict:
    return {
        "id": identifier,
        "priority": priority,
        "asset_id": asset_id or f"asset-{identifier}",
        "est_duration_min": duration,
        "competency": competency,
        "parts": parts or [],
        "tools": tools or [],
    }


def _window(identifier: str = "window-1", *, hours: int = 4, depot_id: str = "depot-1"):
    return {
        "id": identifier,
        "depot_id": depot_id,
        "starts_at": BASE,
        "ends_at": BASE + timedelta(hours=hours),
    }


def _crew(identifier: str, *, depot_id: str = "depot-1", competencies=None):
    return {
        "id": identifier,
        "depot_id": depot_id,
        "competencies": competencies if competencies is not None else ["mechanical"],
    }


def _request(
    work_packages: list[dict],
    *,
    windows: list[dict] | None = None,
    crews: list[dict] | None = None,
    depot_capacity: int = 4,
    **constraints,
) -> PlanRequest:
    return PlanRequest(
        work_packages=work_packages,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=8),
        time_limit_seconds=20,
        windows=windows or [_window()],
        crews=crews or [_crew("crew-1")],
        depots=[{"id": "depot-1", "name": "Depot 1", "capacity": depot_capacity}],
        **constraints,
    )


def _assert_no_overlap(left: dict, right: dict) -> None:
    assert (
        left["window_end"] <= right["window_start"]
        or right["window_end"] <= left["window_start"]
    )


def test_competency_and_crew_unavailability_are_mandatory():
    work = [_work_package("wp-1", competency="electrical")]
    no_skill = solve_plan(_request(work), prefer_cp_sat=False)
    unavailable = solve_plan(
        _request(
            work,
            crews=[_crew("crew-1", competencies=["electrical"])],
            crew_unavailability={
                "crew-1": [{"starts_at": BASE, "ends_at": BASE + timedelta(hours=4)}]
            },
        ),
        prefer_cp_sat=False,
    )

    assert no_skill.feasible is False
    assert unavailable.feasible is False
    assert "wp-1" in no_skill.infeasibility_reasons[0]


def test_asset_unavailability_and_same_asset_non_overlap():
    work = [
        _work_package("wp-1", asset_id="train-1"),
        _work_package("wp-2", asset_id="train-1"),
    ]
    result = solve_plan(
        _request(
            work,
            crews=[_crew("crew-1"), _crew("crew-2")],
            asset_unavailability={
                "train-1": [{"starts_at": BASE, "ends_at": BASE + timedelta(minutes=30)}]
            },
        ),
        prefer_cp_sat=False,
    )

    assert result.feasible
    assert len(result.assignments) == 2
    _assert_no_overlap(*result.assignments)
    assert min(item["window_start"] for item in result.assignments) >= BASE + timedelta(
        minutes=30
    )


def test_depot_capacity_and_tool_capacity_prevent_parallel_work():
    work = [
        _work_package("wp-1", tools=[{"id": "lift", "quantity": 1}]),
        _work_package("wp-2", tools=[{"id": "lift", "quantity": 1}]),
    ]
    result = solve_plan(
        _request(
            work,
            crews=[_crew("crew-1"), _crew("crew-2")],
            depot_capacity=1,
            depot_tools={"depot-1": {"lift": 1}},
        ),
        prefer_cp_sat=False,
    )

    assert result.feasible
    _assert_no_overlap(*result.assignments)


def test_consumable_parts_shortage_is_explicitly_infeasible():
    work = [
        _work_package("wp-1", parts=[{"id": "bearing", "quantity": 1}]),
        _work_package("wp-2", parts=[{"id": "bearing", "quantity": 1}]),
    ]
    result = solve_plan(
        _request(
            work,
            crews=[_crew("crew-1"), _crew("crew-2")],
            depot_parts={"depot-1": {"bearing": 1}},
        ),
        prefer_cp_sat=False,
    )

    assert result.feasible is False
    assert result.infeasibility_reasons


def test_priority_and_objective_breakdown_are_structured():
    work = [
        _work_package("low", priority="LOW", asset_id="train-low"),
        _work_package("critical", priority="CRITICAL", asset_id="train-critical"),
    ]
    result = solve_plan(
        _request(work, crews=[_crew("crew-1")]),
        objective_profile="speed",
        prefer_cp_sat=False,
    )
    by_id = {item["work_package_id"]: item for item in result.assignments}

    assert result.feasible
    assert by_id["critical"]["window_start"] <= by_id["low"]["window_start"]
    assert result.objective_breakdown.keys() >= {
        "profile",
        "makespan_hours",
        "asset_downtime_min",
        "priority_delay_min",
        "overtime_min",
        "travel_min",
        "workload_spread_min",
        "bundled_pairs",
        "objective_score",
    }


def test_fallback_produces_materially_different_alternatives():
    request = _request(
        [_work_package("wp-1"), _work_package("wp-2")],
        crews=[_crew("crew-1"), _crew("crew-2")],
    )
    results = solve_alternatives(
        request,
        alternatives=2,
        objective_profile="balanced",
        prefer_cp_sat=False,
    )

    assert len(results) == 2
    signatures = {
        frozenset(
            (item["work_package_id"], item["crew_id"], item["window_id"])
            for item in result.assignments
        )
        for result in results
    }
    assert len(signatures) == 2
    assert {result.objective_profile for result in results} == {"balanced", "speed"}


def test_single_alternative_keeps_full_time_limit(monkeypatch):
    request = _request([_work_package("wp-1")])
    seen: list[int] = []
    original = solver_module.solve_plan

    def spy(bounded_request, *args, **kwargs):
        seen.append(bounded_request.time_limit_seconds)
        return original(bounded_request, *args, **kwargs)

    monkeypatch.setattr(solver_module, "solve_plan", spy)
    results = solve_alternatives(request, alternatives=1, prefer_cp_sat=False)

    assert results and results[0].feasible
    assert seen == [request.time_limit_seconds]


def test_cp_sat_enforces_same_constraints_when_available():
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except ImportError:
        pytest.skip("OR-Tools native runtime is unavailable")
    request = _request(
        [
            _work_package(
                "wp-1",
                asset_id="train-1",
                tools=[{"id": "lift", "quantity": 1}],
            ),
            _work_package(
                "wp-2",
                asset_id="train-1",
                tools=[{"id": "lift", "quantity": 1}],
            ),
        ],
        crews=[_crew("crew-1"), _crew("crew-2")],
        depot_capacity=1,
        depot_tools={"depot-1": {"lift": 1}},
        asset_unavailability={
            "train-1": [
                {"starts_at": BASE, "ends_at": BASE + timedelta(minutes=30)}
            ]
        },
    )
    result = solve_plan(request, prefer_cp_sat=True)

    assert result.feasible
    _assert_no_overlap(*result.assignments)
    assert min(item["window_start"] for item in result.assignments) >= BASE + timedelta(
        minutes=30
    )


def test_worker_persists_and_lists_multiple_proposals(client, db_session, worker_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[
            ("WP-A", InterventionPriority.HIGH, 60, "mechanical"),
            ("WP-B", InterventionPriority.HIGH, 60, "mechanical"),
        ],
        windows=[(0, 120)],
    )
    db_session.add(
        Crew(
            name="Crew-B",
            competencies=["mechanical"],
            depot_id=scenario["depot"].id,
        )
    )
    db_session.commit()
    payload = plan_payload(scenario)
    payload.update({"alternatives": 2, "objective_profile": "balanced"})

    submitted = client.post("/api/v1/planning/jobs", json=payload)
    assert submitted.status_code == 202
    job_id = submitted.json()["id"]
    assert solver_worker.process_next_job() is True

    db_session.expire_all()
    job = db_session.get(PlanJob, uuid.UUID(job_id))
    proposals = list(
        db_session.scalars(
            select(ScheduleProposal).where(ScheduleProposal.plan_job_id == job.id)
        ).all()
    )
    listed = client.get(f"/api/v1/planning/jobs/{job_id}/proposals")

    assert job.state == JobState.COMPLETED
    assert len(proposals) == 2
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert job.result["requested_alternatives"] == 2
    assert job.result["produced_alternatives"] == 2
    assert all(
        work_package.state == WorkPackageState.PLANNED
        for work_package in scenario["work_packages"]
    )
    assert db_session.scalar(select(ScheduleAssignment)) is not None


def test_worker_reports_supplied_crew_absence_as_infeasible(
    client, db_session, worker_session
):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[
            ("WP-A", InterventionPriority.CRITICAL, 60, "mechanical")
        ],
        windows=[(0, 60)],
    )
    payload = plan_payload(scenario)
    payload["constraints"] = {
        "crew_unavailability": {
            str(scenario["crew"].id): [
                {
                    "starts_at": scenario["windows"][0].starts_at.isoformat(),
                    "ends_at": scenario["windows"][0].ends_at.isoformat(),
                }
            ]
        }
    }

    submitted = client.post("/api/v1/planning/jobs", json=payload)
    assert submitted.status_code == 202
    assert solver_worker.process_next_job() is True

    db_session.expire_all()
    job = db_session.get(PlanJob, uuid.UUID(submitted.json()["id"]))
    assert job.state == JobState.INFEASIBLE
    assert job.result["infeasibility_reasons"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"alternatives": 4},
        {"horizon_end": (BASE - timedelta(hours=1)).isoformat()},
        {"work_package_ids": []},
    ],
)
def test_planning_request_validation(client, db_session, overrides):
    scenario = seed_scenario(
        db_session,
        work_packages=[("WP-A", InterventionPriority.HIGH, 60, "mechanical")],
        windows=[(0, 60)],
    )
    payload = plan_payload(scenario)
    payload.update(overrides)

    response = client.post("/api/v1/planning/jobs", json=payload)
    assert response.status_code == 422
