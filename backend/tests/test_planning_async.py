"""Async planning pipeline tests.

ERD requirements: PLN-01, PLN-02, PLN-03, PLN-04, RPL-01.
"""

import uuid

import pytest
from sqlalchemy import select

from app.domain.enums import InterventionPriority, JobState, ProposalState
from app.domain.models import MaintenanceWindow, PlanJob, ScheduleAssignment, ScheduleProposal
from app.workers import solver_worker
from tests.helpers_planning import plan_payload, reset_queue, seed_scenario


@pytest.fixture()
def worker_session(db_session, monkeypatch):
    """Bind the solver worker to the test session."""
    monkeypatch.setattr(solver_worker, "SessionLocal", lambda: db_session)
    return db_session


def _submit(client, scenario) -> uuid.UUID:
    """Submit a planning job over HTTP and return its identifier."""
    response = client.post("/api/v1/planning/jobs", json=plan_payload(scenario))
    return uuid.UUID(response.json()["id"])


def test_submit_returns_queued_immediately(client, db_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[
            ("WP-CRIT", InterventionPriority.CRITICAL, 60, "mechanical"),
            ("WP-LOW", InterventionPriority.LOW, 30, "mechanical"),
        ],
        windows=[(0, 60), (60, 120)],
    )

    response = client.post("/api/v1/planning/jobs", json=plan_payload(scenario))

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == JobState.QUEUED.value
    assert body["finished_at"] is None
    assert body["result"] is None


def test_worker_produces_proposal(client, db_session, worker_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[
            ("WP-CRIT", InterventionPriority.CRITICAL, 60, "mechanical"),
            ("WP-LOW", InterventionPriority.LOW, 30, "mechanical"),
        ],
        windows=[(0, 60), (60, 120)],
    )
    job_id = _submit(client, scenario)

    assert solver_worker.process_next_job() is True

    db_session.expire_all()
    job = db_session.get(PlanJob, job_id)
    assert job.state == JobState.COMPLETED
    assert job.started_at is not None
    assert job.finished_at is not None

    proposals = list(
        db_session.scalars(
            select(ScheduleProposal).where(ScheduleProposal.plan_job_id == job.id)
        ).all()
    )
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.state == ProposalState.PROPOSED
    assert proposal.summary["work_package_count"] == 2

    assignments = list(
        db_session.scalars(
            select(ScheduleAssignment).where(ScheduleAssignment.proposal_id == proposal.id)
        ).all()
    )
    assert len(assignments) == 2
    assert {assignment.work_package_id for assignment in assignments} == {
        work_package.id for work_package in scenario["work_packages"]
    }

    windows = list(db_session.scalars(select(MaintenanceWindow)).all())
    for assignment in assignments:
        assert assignment.window_start is not None
        assert assignment.window_end is not None
        within = any(
            window.starts_at <= assignment.window_start and assignment.window_end <= window.ends_at
            for window in windows
        )
        assert within


def test_infeasible_job_records_reasons(client, db_session, worker_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[("WP-BIG", InterventionPriority.CRITICAL, 100000, "mechanical")],
        windows=[(0, 60), (60, 120)],
    )
    job_id = _submit(client, scenario)

    assert solver_worker.process_next_job() is True

    db_session.expire_all()
    job = db_session.get(PlanJob, job_id)
    assert job.state == JobState.INFEASIBLE
    assert job.result["infeasibility_reasons"]
    assert job.finished_at is not None
    proposals = list(
        db_session.scalars(
            select(ScheduleProposal).where(ScheduleProposal.plan_job_id == job.id)
        ).all()
    )
    assert proposals == []


def test_cancel_before_processing_is_skipped(client, db_session, worker_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[("WP-CRIT", InterventionPriority.CRITICAL, 60, "mechanical")],
        windows=[(0, 60)],
    )
    job_id = _submit(client, scenario)

    cancelled = client.post(f"/api/v1/planning/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == JobState.CANCELLED.value

    assert solver_worker.process_next_job() is True

    db_session.expire_all()
    job = db_session.get(PlanJob, job_id)
    assert job.state == JobState.CANCELLED
    assert job.finished_at is not None
    proposals = list(
        db_session.scalars(
            select(ScheduleProposal).where(ScheduleProposal.plan_job_id == job.id)
        ).all()
    )
    assert proposals == []


def test_invalidate_preserves_assignments_and_enqueues_replan(client, db_session, worker_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[("WP-CRIT", InterventionPriority.CRITICAL, 60, "mechanical")],
        windows=[(0, 60)],
    )
    _submit(client, scenario)
    assert solver_worker.process_next_job() is True

    db_session.expire_all()
    proposal = db_session.scalars(select(ScheduleProposal)).first()
    assert proposal is not None
    before = {
        assignment.id: (assignment.work_package_id, assignment.window_start, assignment.window_end)
        for assignment in db_session.scalars(
            select(ScheduleAssignment).where(ScheduleAssignment.proposal_id == proposal.id)
        ).all()
    }
    assert before

    response = client.post(
        f"/api/v1/planning/proposals/{proposal.id}/invalidate",
        json={"trigger": "crew_absence", "reason": "crew unavailable"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["proposal_state"] == ProposalState.INVALIDATED.value
    assert body["replan_job_id"]

    db_session.expire_all()
    refreshed = db_session.get(ScheduleProposal, proposal.id)
    assert refreshed.state == ProposalState.INVALIDATED

    after = {
        assignment.id: (assignment.work_package_id, assignment.window_start, assignment.window_end)
        for assignment in db_session.scalars(
            select(ScheduleAssignment).where(ScheduleAssignment.proposal_id == proposal.id)
        ).all()
    }
    assert after == before

    replan_job = db_session.get(PlanJob, uuid.UUID(body["replan_job_id"]))
    assert replan_job.state == JobState.QUEUED
    assert replan_job.request["replan_of"] == str(proposal.id)
    assert replan_job.request["trigger"] == "crew_absence"
    assert replan_job.request["work_package_ids"] == [str(scenario["work_packages"][0].id)]


def test_unknown_work_package_is_rejected(client, db_session):
    reset_queue()
    scenario = seed_scenario(
        db_session,
        work_packages=[("WP-CRIT", InterventionPriority.CRITICAL, 60, "mechanical")],
        windows=[(0, 60)],
    )
    payload = plan_payload(scenario)
    payload["work_package_ids"].append(str(uuid.uuid4()))

    response = client.post("/api/v1/planning/jobs", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["unknown_work_package_ids"]
