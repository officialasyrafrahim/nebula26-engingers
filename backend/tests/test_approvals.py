"""Human approval and publication tests.

ERD requirements: HUM-01, AUD-01, AUD-02.
"""

import uuid

from sqlalchemy import select

from app.domain.enums import ApprovalDecision, ProposalState
from app.domain.models import Approval, AuditLog, PublishedSchedule, ScheduleProposal
from tests.helpers_planning import seed_proposal


def test_approve_proposal_records_audit(client, db_session):
    scenario = seed_proposal(db_session)
    proposal_id = scenario["proposal"].id

    response = client.post(
        "/api/v1/approvals",
        json={"proposal_id": str(proposal_id), "decision": "APPROVED", "comment": "looks good"},
        headers={"x-user-role": "PLANNER", "x-user-id": "planner-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["proposal_id"] == str(proposal_id)
    assert body["role"] == "PLANNER"
    assert body["decision"] == ApprovalDecision.APPROVED.value

    db_session.expire_all()
    proposal = db_session.get(ScheduleProposal, proposal_id)
    assert proposal.state == ProposalState.APPROVED
    audits = list(
        db_session.scalars(
            select(AuditLog).where(AuditLog.action == "approval_decision")
        ).all()
    )
    assert len(audits) == 1
    assert audits[0].actor == "planner-1"
    assert audits[0].after["decision"] == ApprovalDecision.APPROVED.value


def test_technician_cannot_approve(client, db_session):
    scenario = seed_proposal(db_session)

    response = client.post(
        "/api/v1/approvals",
        json={"proposal_id": str(scenario["proposal"].id), "decision": "APPROVED"},
        headers={"x-user-role": "TECHNICIAN"},
    )

    assert response.status_code == 403


def test_publish_requires_and_records_approval(client, db_session):
    scenario = seed_proposal(db_session)
    proposal_id = scenario["proposal"].id

    blocked = client.post(
        "/api/v1/schedules/publish",
        json={"proposal_id": str(proposal_id)},
        headers={"x-user-role": "PLANNER"},
    )
    assert blocked.status_code == 409

    approval_response = client.post(
        "/api/v1/approvals",
        json={"proposal_id": str(proposal_id), "decision": "APPROVED", "comment": "approved"},
        headers={"x-user-role": "PLANNER", "x-user-id": "planner-2"},
    )
    assert approval_response.status_code == 201

    published = client.post(
        "/api/v1/schedules/publish",
        json={"proposal_id": str(proposal_id)},
        headers={"x-user-role": "PLANNER", "x-user-id": "planner-2"},
    )
    assert published.status_code == 201
    body = published.json()
    assert body["proposal_id"] == str(proposal_id)
    assert body["approval_id"] == approval_response.json()["id"]
    assert body["published_by"] == "planner-2"

    db_session.expire_all()
    proposal = db_session.get(ScheduleProposal, proposal_id)
    assert proposal.state == ProposalState.PUBLISHED

    stored_approval = db_session.get(Approval, uuid.UUID(approval_response.json()["id"]))
    assert stored_approval.decision == ApprovalDecision.APPROVED
    assert stored_approval.comment == "approved"
    assert stored_approval.actor == "planner-2"

    rows = list(db_session.scalars(select(PublishedSchedule)).all())
    assert len(rows) == 1
    assert rows[0].proposal_id == proposal_id

    listed = client.get("/api/v1/schedules/published")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_reject_proposal(client, db_session):
    scenario = seed_proposal(db_session)
    proposal_id = scenario["proposal"].id

    response = client.post(
        "/api/v1/approvals",
        json={"proposal_id": str(proposal_id), "decision": "REJECTED"},
        headers={"x-user-role": "ADMIN"},
    )

    assert response.status_code == 201
    db_session.expire_all()
    proposal = db_session.get(ScheduleProposal, proposal_id)
    assert proposal.state == ProposalState.REJECTED


def test_list_approvals_filters(client, db_session):
    scenario = seed_proposal(db_session)
    proposal_id = scenario["proposal"].id
    client.post(
        "/api/v1/approvals",
        json={"proposal_id": str(proposal_id), "decision": "APPROVED"},
        headers={"x-user-role": "PLANNER"},
    )

    by_proposal = client.get(f"/api/v1/approvals?proposal_id={proposal_id}")
    assert by_proposal.status_code == 200
    assert len(by_proposal.json()) == 1

    by_other = client.get(f"/api/v1/approvals?proposal_id={uuid.uuid4()}")
    assert by_other.status_code == 200
    assert by_other.json() == []
