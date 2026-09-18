"""Execution, integration, registry and assistant tests.

ERD requirements: EXE-01, FBK-01, INT-01, AI-01, ML-02, SEC-01.
"""

import uuid

from app.domain.enums import InterventionPriority, WorkPackageState
from app.domain.models import Assessment, ConditionEvent, WorkPackage
from tests.helpers_planning import seed_scenario


def _seed_one(db_session, priority=InterventionPriority.CRITICAL, duration=60):
    return seed_scenario(
        db_session,
        work_packages=[("WP-1", priority, duration, "mechanical")],
        windows=[(0, 60)],
    )


def test_work_package_lifecycle(client, db_session):
    scenario = _seed_one(db_session)
    work_package_id = str(scenario["work_packages"][0].id)

    approved = client.post(
        "/api/v1/approvals",
        json={"work_package_id": work_package_id, "decision": "APPROVED"},
        headers={"x-user-role": "PLANNER"},
    )
    assert approved.status_code == 201

    db_session.expire_all()
    assert db_session.get(WorkPackage, uuid.UUID(work_package_id)).state == (
        WorkPackageState.APPROVED
    )

    assigned = client.post(
        f"/api/v1/work-packages/{work_package_id}/assign",
        json={"technician_id": None, "crew_id": str(scenario["crew"].id)},
        headers={"x-user-role": "PLANNER"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["state"] == WorkPackageState.ASSIGNED.value
    assert assigned.json()["assigned_crew_id"] == str(scenario["crew"].id)

    started = client.post(
        f"/api/v1/work-packages/{work_package_id}/start",
        headers={"x-user-role": "TECHNICIAN"},
    )
    assert started.status_code == 200
    assert started.json()["state"] == WorkPackageState.IN_PROGRESS.value

    completed = client.post(
        f"/api/v1/work-packages/{work_package_id}/complete",
        headers={"x-user-role": "TECHNICIAN"},
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == WorkPackageState.COMPLETED.value


def test_outcome_links_prediction_without_mutating_it(client, db_session):
    scenario = _seed_one(db_session)
    work_package = scenario["work_packages"][0]
    condition_event = scenario["condition_event"]
    assessment = scenario["assessment"]
    original_score = condition_event.score
    original_recommendation = assessment.recommendation

    response = client.post(
        "/api/v1/outcomes",
        json={
            "work_package_id": str(work_package.id),
            "finding_type": "FAULT_NOT_FOUND",
            "actual_finding": "no fault detected on inspection",
        },
        headers={"x-user-role": "TECHNICIAN", "x-user-id": "tech-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["finding_type"] == "FAULT_NOT_FOUND"
    assert body["condition_event_id"] == str(condition_event.id)

    db_session.expire_all()
    refreshed_event = db_session.get(ConditionEvent, condition_event.id)
    refreshed_assessment = db_session.get(Assessment, assessment.id)
    refreshed_work_package = db_session.get(WorkPackage, work_package.id)
    assert refreshed_event.score == original_score
    assert refreshed_assessment.recommendation == original_recommendation
    assert refreshed_work_package.priority == work_package.priority

    listed = client.get("/api/v1/outcomes")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_writeback_requires_approval(client, db_session):
    scenario = _seed_one(db_session)
    work_package_id = str(scenario["work_packages"][0].id)

    blocked = client.post(
        f"/api/v1/integration/writeback/{work_package_id}",
        headers={"x-user-role": "PLANNER"},
    )
    assert blocked.status_code == 409

    client.post(
        "/api/v1/approvals",
        json={"work_package_id": work_package_id, "decision": "APPROVED"},
        headers={"x-user-role": "PLANNER"},
    )

    written = client.post(
        f"/api/v1/integration/writeback/{work_package_id}",
        headers={"x-user-role": "PLANNER"},
    )
    assert written.status_code == 200
    body = written.json()
    assert body["written_back"] is True
    assert body["external_ref"]


def test_integration_sync_and_adapters(client, db_session):
    adapters = client.get("/api/v1/integration/adapters")
    assert adapters.status_code == 200
    assert adapters.json() == [
        {
            "name": "cmms-mock",
            "kind": "cmms",
            "mode": "simulated",
            "write_back": "explicit-approved-only",
        }
    ]

    synced = client.post("/api/v1/integration/sync")
    assert synced.status_code == 200
    assert synced.json()["assets_synced"] == 1
    assert synced.json()["work_orders_fetched"] == 1


def test_model_registry_separation_of_duties(client, db_session):
    registered = client.post(
        "/api/v1/model-registry",
        json={"name": "vibration-detector", "version": "1.0.0", "fleet": "Fleet-A"},
    )
    assert registered.status_code == 201
    body = registered.json()
    assert body["approval_state"] == "CANDIDATE"
    model_id = body["id"]

    forbidden = client.post(
        f"/api/v1/model-registry/{model_id}/approve",
        headers={"x-user-role": "PLANNER"},
    )
    assert forbidden.status_code == 403

    approved = client.post(
        f"/api/v1/model-registry/{model_id}/approve",
        headers={"x-user-role": "MODEL_APPROVER", "x-user-id": "approver-1"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval_state"] == "APPROVED"

    listed = client.get("/api/v1/model-registry")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_assistant_explanation_is_evidence_grounded(client, db_session):
    scenario = _seed_one(db_session)
    assessment_id = scenario["assessment"].id

    response = client.get(f"/api/v1/assistant/explain/assessment/{assessment_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["llm_used"] is False
    assert body["llm_status"] == "disabled"
    assert body["llm_explanation"] is None
    assert body["evidence"]
    assert body["evidence"][0]["type"] == "MODEL_INFERENCE"
    assert body["recommendation"] == scenario["assessment"].recommendation.value
    assert body["priority"] == scenario["assessment"].priority.value
    assert body["explanation"]
