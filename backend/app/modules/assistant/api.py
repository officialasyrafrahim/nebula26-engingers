"""Optional read-only assistant API.

ERD requirements: AI-01.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.modules.assistant import service
from app.modules.assistant.llm import LlmRuntime, build_llm_runtime
from app.modules.assistant.schemas import (
    AssistantExplanationResponse,
    AssistantQuestionRequest,
    AssistantQuestionResponse,
)

router = APIRouter(prefix="/api/v1", tags=["assistant"])


def get_assistant_runtime(settings: Settings = Depends(get_settings)) -> LlmRuntime:
    """Resolve the optional provider from runtime settings."""
    return build_llm_runtime(settings)


@router.get(
    "/assistant/explain/assessment/{assessment_id}",
    response_model=AssistantExplanationResponse,
)
def explain_assessment(
    assessment_id: uuid.UUID,
    db: Session = Depends(get_db),
    runtime: LlmRuntime = Depends(get_assistant_runtime),
    user: CurrentUser = Depends(
        require_role(UserRole.PLANNER, UserRole.ENGINEER, UserRole.ADMIN)
    ),
) -> AssistantExplanationResponse:
    """Explain an assessment from persisted evidence with optional LLM context."""
    return service.explain_assessment(db, assessment_id, runtime)


@router.post("/assistant/questions", response_model=AssistantQuestionResponse)
def answer_question(
    request: AssistantQuestionRequest,
    db: Session = Depends(get_db),
    runtime: LlmRuntime = Depends(get_assistant_runtime),
    user: CurrentUser = Depends(
        require_role(UserRole.PLANNER, UserRole.ENGINEER, UserRole.ADMIN)
    ),
) -> AssistantQuestionResponse:
    """Answer a question using only explicitly scoped persisted records."""
    return service.answer_question(db, request, runtime)
