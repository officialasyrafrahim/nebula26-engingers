"""Read-only structured context and optional LLM explanations.

ERD requirements: AI-01.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import (
    Approval,
    Assessment,
    Asset,
    Component,
    ConditionEvent,
    Crew,
    Depot,
    Evidence,
    MaintenanceOutcome,
    PlanInvalidation,
    PublishedSchedule,
    ScheduleAssignment,
    ScheduleProposal,
    WorkPackage,
)
from app.modules.assistant.llm import (
    SYSTEM_PROMPT,
    LlmRuntime,
    build_user_prompt,
)
from app.modules.assistant.schemas import AssistantQuestionRequest

logger = logging.getLogger(__name__)


def explain_assessment(
    db: Session,
    assessment_id: uuid.UUID,
    runtime: LlmRuntime | None = None,
) -> dict:
    """Explain persisted evidence and optionally add an LLM interpretation."""
    runtime = runtime or LlmRuntime.disabled()
    context = build_assessment_context(db, assessment_id)
    assessment = context["assessment"]
    evidence = context["evidence"]
    explanation = (
        f"Assessment recommends {assessment['recommendation']} at "
        f"{assessment['priority']} priority with a maintenance horizon of "
        f"{_available(assessment['horizon_hours'], suffix=' hours')}. "
        f"Supported by {len(evidence)} persisted evidence item(s)."
    )
    llm_text, llm_status = _complete(
        runtime,
        question=(
            "Explain this assessment, its principal evidence and uncertainty, and list only "
            "planner considerations supported by the context."
        ),
        context=context,
    )
    return {
        "assessment_id": assessment_id,
        "recommendation": assessment["recommendation"],
        "priority": assessment["priority"],
        "explanation": explanation,
        "evidence": evidence,
        "llm_used": llm_text is not None,
        "llm_status": llm_status,
        "llm_explanation": llm_text,
    }


def answer_question(
    db: Session,
    request: AssistantQuestionRequest,
    runtime: LlmRuntime | None = None,
) -> dict:
    """Answer a scoped question or return the verified context as fallback."""
    runtime = runtime or LlmRuntime.disabled()
    context = build_question_context(db, request)
    llm_text, llm_status = _complete(
        runtime,
        question=request.question,
        context=context,
    )
    if llm_text is None:
        scopes = ", ".join(context)
        answer = (
            f"The optional LLM context layer is {llm_status}; no generated answer is "
            f"available. Verified structured context for {scopes} is returned for review."
        )
    else:
        answer = llm_text
    return {
        "question": request.question,
        "answer": answer,
        "llm_used": llm_text is not None,
        "llm_status": llm_status,
        "structured_context": context,
    }


def build_question_context(db: Session, request: AssistantQuestionRequest) -> dict:
    """Load only the persisted records explicitly scoped by the caller."""
    context: dict = {}
    if request.assessment_id is not None:
        context["assessment_scope"] = build_assessment_context(db, request.assessment_id)
    if request.work_package_id is not None:
        context["work_package_scope"] = build_work_package_context(db, request.work_package_id)
    if request.proposal_id is not None:
        context["proposal_scope"] = build_proposal_context(db, request.proposal_id)
    return context


def build_assessment_context(db: Session, assessment_id: uuid.UUID) -> dict:
    """Build traceable assessment context without generating operational facts."""
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="assessment not found")
    condition = db.get(ConditionEvent, assessment.condition_event_id)
    if condition is None:
        raise HTTPException(status_code=409, detail="assessment condition event is unavailable")
    component = db.get(Component, condition.component_id)
    asset = db.get(Asset, component.asset_id) if component is not None else None
    evidence_rows = list(
        db.scalars(
            select(Evidence).where(
                (Evidence.assessment_id == assessment.id)
                | (Evidence.condition_event_id == assessment.condition_event_id)
            )
        ).all()
    )
    work_packages = list(
        db.scalars(select(WorkPackage).where(WorkPackage.assessment_id == assessment.id)).all()
    )
    outcomes = _outcomes_for_work_packages(db, work_packages)
    return {
        "assessment": {
            "id": str(assessment.id),
            "recommendation": assessment.recommendation.value,
            "priority": assessment.priority.value,
            "horizon_hours": assessment.horizon_hours,
            "rationale": assessment.rationale or {},
            "assessed_at": _timestamp(assessment.assessed_at),
        },
        "condition_event": {
            "id": str(condition.id),
            "score": condition.score,
            "trend": condition.trend.value,
            "data_quality": condition.data_quality.value,
            "detected_at": _timestamp(condition.detected_at),
            "model_version_id": _identifier(condition.model_version_id),
        },
        "component": _component_record(component),
        "asset": _asset_record(asset),
        "evidence": [
            {
                "id": str(row.id),
                "type": row.type.value,
                "content": row.content or {},
            }
            for row in evidence_rows
        ],
        "work_packages": [
            _work_package_record(row, outcomes.get(row.id, [])) for row in work_packages
        ],
    }


def build_work_package_context(db: Session, work_package_id: uuid.UUID) -> dict:
    """Build work-package context linked back to its original assessment."""
    work_package = db.get(WorkPackage, work_package_id)
    if work_package is None:
        raise HTTPException(status_code=404, detail="work package not found")
    outcomes = _outcomes_for_work_packages(db, [work_package]).get(work_package.id, [])
    return {
        "work_package": _work_package_record(work_package, outcomes),
        "originating_assessment": build_assessment_context(db, work_package.assessment_id),
    }


def build_proposal_context(db: Session, proposal_id: uuid.UUID) -> dict:
    """Build persisted solver, assignment and approval context for a proposal."""
    proposal = db.get(ScheduleProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="schedule proposal not found")
    assignments = list(
        db.scalars(
            select(ScheduleAssignment).where(ScheduleAssignment.proposal_id == proposal.id)
        ).all()
    )
    approvals = list(
        db.scalars(select(Approval).where(Approval.proposal_id == proposal.id)).all()
    )
    published = list(
        db.scalars(
            select(PublishedSchedule).where(PublishedSchedule.proposal_id == proposal.id)
        ).all()
    )
    invalidations = list(
        db.scalars(
            select(PlanInvalidation).where(PlanInvalidation.proposal_id == proposal.id)
        ).all()
    )
    plan_job = proposal.plan_job
    assignment_context = []
    for assignment in assignments:
        work_package = db.get(WorkPackage, assignment.work_package_id)
        crew = db.get(Crew, assignment.crew_id) if assignment.crew_id else None
        depot = db.get(Depot, assignment.depot_id) if assignment.depot_id else None
        assignment_context.append(
            {
                "id": str(assignment.id),
                "work_package": _work_package_record(work_package, [])
                if work_package is not None
                else None,
                "crew": {"id": str(crew.id), "name": crew.name} if crew else None,
                "depot": {"id": str(depot.id), "name": depot.name} if depot else None,
                "window_start": _timestamp(assignment.window_start),
                "window_end": _timestamp(assignment.window_end),
            }
        )
    return {
        "proposal": {
            "id": str(proposal.id),
            "state": proposal.state.value,
            "summary": proposal.summary or {},
            "plan_job": (
                {
                    "id": str(plan_job.id),
                    "state": plan_job.state.value,
                    "request": plan_job.request or {},
                    "result": plan_job.result,
                }
                if plan_job is not None
                else None
            ),
        },
        "assignments": assignment_context,
        "approvals": [
            {
                "id": str(row.id),
                "decision": row.decision.value,
                "actor": row.actor,
                "role": row.role.value,
                "comment": row.comment,
                "decided_at": _timestamp(row.decided_at),
            }
            for row in approvals
        ],
        "published_schedules": [
            {
                "id": str(row.id),
                "approval_id": str(row.approval_id),
                "published_at": _timestamp(row.published_at),
                "published_by": row.published_by,
            }
            for row in published
        ],
        "invalidations": [
            {
                "id": str(row.id),
                "trigger": row.trigger,
                "reason": row.reason,
                "detected_at": _timestamp(row.detected_at),
            }
            for row in invalidations
        ],
    }


def _complete(runtime: LlmRuntime, *, question: str, context: dict) -> tuple[str | None, str]:
    if runtime.provider is None:
        return None, runtime.fallback_status or "unavailable"
    prompt = build_user_prompt(
        question=question,
        context=context,
        max_context_chars=runtime.max_context_chars,
    )
    try:
        return (
            runtime.provider.complete(system_prompt=SYSTEM_PROMPT, user_prompt=prompt),
            "ok",
        )
    except Exception as exc:
        logger.warning(
            "Optional LLM provider unavailable: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None, "unavailable"


def _outcomes_for_work_packages(
    db: Session, work_packages: list[WorkPackage]
) -> dict[uuid.UUID, list[MaintenanceOutcome]]:
    ids = [row.id for row in work_packages]
    if not ids:
        return {}
    outcomes = list(
        db.scalars(
            select(MaintenanceOutcome).where(MaintenanceOutcome.work_package_id.in_(ids))
        ).all()
    )
    grouped: dict[uuid.UUID, list[MaintenanceOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault(outcome.work_package_id, []).append(outcome)
    return grouped


def _work_package_record(
    work_package: WorkPackage,
    outcomes: list[MaintenanceOutcome],
) -> dict:
    return {
        "id": str(work_package.id),
        "title": work_package.title,
        "description": work_package.description,
        "recommended_action": work_package.recommended_action,
        "priority": work_package.priority.value,
        "state": work_package.state.value,
        "competency": work_package.competency,
        "estimated_duration_min": work_package.est_duration_min,
        "tools": work_package.tools,
        "parts": work_package.parts,
        "assigned_technician_id": _identifier(work_package.assigned_technician_id),
        "assigned_crew_id": _identifier(work_package.assigned_crew_id),
        "outcomes": [
            {
                "id": str(outcome.id),
                "finding_type": outcome.finding_type.value,
                "actual_finding": outcome.actual_finding,
                "actual_duration_min": outcome.actual_duration_min,
                "parts_used": outcome.parts_used,
                "recorded_at": _timestamp(outcome.recorded_at),
            }
            for outcome in outcomes
        ],
    }


def _component_record(component: Component | None) -> dict | None:
    if component is None:
        return None
    return {
        "id": str(component.id),
        "component_type": component.component_type.value,
        "serial": component.serial,
    }


def _asset_record(asset: Asset | None) -> dict | None:
    if asset is None:
        return None
    return {
        "id": str(asset.id),
        "fleet": asset.fleet,
        "label": asset.label,
        "asset_type": asset.asset_type,
        "source_system": asset.source_system,
        "source_id": asset.source_id,
    }


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _identifier(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _available(value: object | None, *, suffix: str = "") -> str:
    return f"{value}{suffix}" if value is not None else "unavailable"
