"""Approvals service.

ERD requirements: HUM-01, HUM-02, AUD-02.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.security import CurrentUser
from app.domain.enums import ApprovalDecision, ProposalState, WorkPackageState
from app.domain.models import Approval, PublishedSchedule, ScheduleProposal, WorkPackage, utcnow
from app.domain.schemas import ApprovalCreate


def decide_approval(db: Session, data: ApprovalCreate, user: CurrentUser) -> Approval:
    """Record a human approve/modify/reject decision."""
    proposal: ScheduleProposal | None = None
    if data.proposal_id is not None:
        proposal = db.get(ScheduleProposal, data.proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")

    work_package: WorkPackage | None = None
    if data.work_package_id is not None:
        work_package = db.get(WorkPackage, data.work_package_id)
        if work_package is None:
            raise HTTPException(status_code=404, detail="work package not found")

    approval = Approval(
        proposal_id=data.proposal_id,
        work_package_id=data.work_package_id,
        actor=user.id,
        role=user.role,
        decision=data.decision,
        comment=data.comment,
        decided_at=utcnow(),
    )
    db.add(approval)
    db.flush()

    # TODO(HUM-01): applying a modified schedule is not yet implemented.
    if proposal is not None:
        if data.decision == ApprovalDecision.APPROVED:
            proposal.state = ProposalState.APPROVED
        elif data.decision == ApprovalDecision.REJECTED:
            proposal.state = ProposalState.REJECTED
    if work_package is not None and data.decision == ApprovalDecision.APPROVED:
        work_package.state = WorkPackageState.APPROVED

    record_audit(
        db,
        actor=user.id,
        action="approval_decision",
        entity_type="approval",
        entity_id=approval.id,
        after={
            "decision": data.decision.value,
            "role": user.role.value,
            "proposal_id": str(data.proposal_id) if data.proposal_id else None,
            "work_package_id": str(data.work_package_id) if data.work_package_id else None,
        },
    )
    db.commit()
    db.refresh(approval)
    return approval


def publish_schedule(
    db: Session,
    proposal_id: uuid.UUID,
    approval_id: uuid.UUID | None = None,
    published_by: str = "system",
) -> PublishedSchedule:
    """Publish an approved schedule as a separate linked record."""
    proposal = db.get(ScheduleProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")

    approval: Approval | None = None
    if approval_id is not None:
        approval = db.get(Approval, approval_id)
    if approval is None:
        approval = db.scalars(
            select(Approval)
            .where(
                Approval.proposal_id == proposal_id,
                Approval.decision == ApprovalDecision.APPROVED,
            )
            .order_by(Approval.decided_at.desc())
        ).first()
    if approval is None or approval.decision != ApprovalDecision.APPROVED:
        raise HTTPException(status_code=409, detail="proposal has no approved decision")

    published = PublishedSchedule(
        proposal_id=proposal.id,
        approval_id=approval.id,
        published_at=utcnow(),
        published_by=published_by,
    )
    db.add(published)
    proposal.state = ProposalState.PUBLISHED
    db.flush()
    record_audit(
        db,
        actor=published_by,
        action="publish_schedule",
        entity_type="published_schedule",
        entity_id=published.id,
        after={"proposal_id": str(proposal.id), "approval_id": str(approval.id)},
    )
    db.commit()
    db.refresh(published)
    return published


def list_approvals(
    db: Session,
    work_package_id: uuid.UUID | None = None,
    proposal_id: uuid.UUID | None = None,
) -> list[Approval]:
    """List approvals with optional filters."""
    statement = select(Approval).order_by(Approval.decided_at.desc())
    if work_package_id is not None:
        statement = statement.where(Approval.work_package_id == work_package_id)
    if proposal_id is not None:
        statement = statement.where(Approval.proposal_id == proposal_id)
    return list(db.scalars(statement).all())


def list_published(db: Session) -> list[PublishedSchedule]:
    """List published schedules."""
    statement = select(PublishedSchedule).order_by(PublishedSchedule.published_at.desc())
    return list(db.scalars(statement).all())
