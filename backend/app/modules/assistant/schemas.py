"""Assistant API schemas."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AssistantExplanationResponse(BaseModel):
    """Deterministic assessment explanation with optional LLM context."""

    assessment_id: uuid.UUID
    recommendation: str
    priority: str
    explanation: str
    evidence: list[dict[str, Any]]
    llm_used: bool
    llm_status: Literal["disabled", "unconfigured", "ok", "unavailable"]
    llm_explanation: str | None = None


class AssistantQuestionRequest(BaseModel):
    """A question bounded to persisted operational records."""

    question: str = Field(min_length=1, max_length=2_000)
    assessment_id: uuid.UUID | None = None
    work_package_id: uuid.UUID | None = None
    proposal_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_context_scope(self) -> AssistantQuestionRequest:
        if not any((self.assessment_id, self.work_package_id, self.proposal_id)):
            raise ValueError("at least one context identifier is required")
        return self


class AssistantQuestionResponse(BaseModel):
    """Grounded answer or structured fallback when no LLM is available."""

    question: str
    answer: str
    llm_used: bool
    llm_status: Literal["disabled", "unconfigured", "ok", "unavailable"]
    structured_context: dict[str, Any]
