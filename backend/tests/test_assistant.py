"""Optional LLM context layer tests.

ERD requirement: AI-01.
"""

import json

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.domain.enums import InterventionPriority
from app.domain.models import Assessment, AuditLog, Evidence
from app.modules.assistant import service
from app.modules.assistant.llm import (
    LlmConfig,
    LlmMalformedResponseError,
    LlmRuntime,
    LlmUnavailableError,
    OpenAICompatibleProvider,
    build_llm_runtime,
    build_user_prompt,
)
from app.modules.assistant.schemas import AssistantQuestionRequest
from tests.helpers_planning import seed_scenario


class StubProvider:
    """Capture a provider request and return fixed grounded text."""

    def __init__(self, answer: str = "Review the persisted vibration evidence.") -> None:
        self.answer = answer
        self.system_prompt = ""
        self.user_prompt = ""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.answer


class UnavailableProvider:
    """Simulate a provider outage."""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        raise LlmUnavailableError("offline")


class MalformedProvider:
    """Simulate a provider response that has no usable content."""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        raise LlmMalformedResponseError("missing content")


def _seed_context(db_session):
    return seed_scenario(
        db_session,
        work_packages=[
            ("Inspect door actuator", InterventionPriority.CRITICAL, 60, "mechanical")
        ],
        windows=[(0, 60)],
    )


def _config(**overrides) -> LlmConfig:
    defaults = {
        "enabled": True,
        "base_url": "https://llm.example/v1",
        "api_key": "secret",
        "api_key_required": True,
        "model": "compatible-model",
        "timeout_seconds": 3.0,
        "max_tokens": 250,
        "send_temperature": True,
        "temperature": 0.0,
        "token_limit_parameter": "max_tokens",
        "max_context_chars": 10_000,
    }
    defaults.update(overrides)
    return LlmConfig(**defaults)


def test_openai_compatible_provider_uses_chat_completions_contract():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Grounded answer"}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), client)
        answer = provider.complete(system_prompt="guardrails", user_prompt="question")

    request = captured["request"]
    payload = json.loads(request.content)
    assert answer == "Grounded answer"
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    assert payload["model"] == "compatible-model"
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 250
    assert payload["messages"] == [
        {"role": "system", "content": "guardrails"},
        {"role": "user", "content": "question"},
    ]


def test_provider_supports_keyless_reasoning_style_request_fields():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    config = _config(
        api_key=None,
        api_key_required=False,
        send_temperature=False,
        token_limit_parameter="max_completion_tokens",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        OpenAICompatibleProvider(config, client).complete(
            system_prompt="guardrails", user_prompt="question"
        )

    request = captured["request"]
    payload = json.loads(request.content)
    assert "authorization" not in request.headers
    assert "temperature" not in payload
    assert payload["max_completion_tokens"] == 250
    assert "max_tokens" not in payload


def test_provider_maps_transport_timeout_to_unavailable():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        provider = OpenAICompatibleProvider(_config(), client)
        with pytest.raises(LlmUnavailableError):
            provider.complete(system_prompt="guardrails", user_prompt="question")


def test_user_prompt_bounds_context_and_redacts_identity_fields():
    prompt = build_user_prompt(
        question="Explain the evidence",
        context={
            "assessment": {"id": "assessment-1", "priority": "HIGH"},
            "approval": {"actor": "person@example", "comment": "private note"},
            "padding": "x" * 200,
        },
        max_context_chars=120,
    )

    assert "assessment-1" in prompt
    assert "person@example" not in prompt
    assert "private note" not in prompt
    assert "[context truncated]" in prompt


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"unexpected": "shape"},
    ],
)
def test_openai_compatible_provider_rejects_malformed_content(body):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleProvider(_config(), client)
        with pytest.raises(LlmMalformedResponseError):
            provider.complete(system_prompt="guardrails", user_prompt="question")


def test_runtime_is_opt_in_and_reports_unconfigured():
    disabled = build_llm_runtime(Settings(assistant_llm_enabled=False))
    unconfigured = build_llm_runtime(
        Settings(assistant_llm_enabled=True, assistant_llm_api_key=None)
    )
    replacement = build_llm_runtime(
        Settings(
            assistant_llm_enabled=True,
            assistant_llm_base_url="http://local-model/v1",
            assistant_llm_api_key=None,
            assistant_llm_api_key_required=False,
        )
    )

    assert disabled.provider is None
    assert disabled.fallback_status == "disabled"
    assert unconfigured.provider is None
    assert unconfigured.fallback_status == "unconfigured"
    assert isinstance(replacement.provider, OpenAICompatibleProvider)


def test_question_endpoint_returns_structured_fallback_when_disabled(client, db_session):
    scenario = _seed_context(db_session)
    response = client.post(
        "/api/v1/assistant/questions",
        json={
            "question": "Why is this maintenance urgent?",
            "assessment_id": str(scenario["assessment"].id),
        },
        headers={"x-user-role": "ENGINEER"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["llm_used"] is False
    assert body["llm_status"] == "disabled"
    assert "no generated answer" in body["answer"]
    assert body["structured_context"]["assessment_scope"]["condition_event"][
        "data_quality"
    ] == "CURRENT"


def test_question_endpoint_requires_context_and_authorized_role(client):
    missing_context = client.post(
        "/api/v1/assistant/questions",
        json={"question": "What should I review?"},
    )
    forbidden = client.post(
        "/api/v1/assistant/questions",
        json={"question": "What should I review?", "assessment_id": "0" * 32},
        headers={"x-user-role": "TECHNICIAN"},
    )

    assert missing_context.status_code == 422
    assert forbidden.status_code == 403


def test_llm_question_is_grounded_and_read_only(db_session):
    scenario = _seed_context(db_session)
    assessment = scenario["assessment"]
    evidence_count = db_session.scalar(select(func.count()).select_from(Evidence))
    audit_count = db_session.scalar(select(func.count()).select_from(AuditLog))
    provider = StubProvider()
    request = AssistantQuestionRequest(
        question="What evidence supports the recommendation?",
        assessment_id=assessment.id,
    )

    result = service.answer_question(
        db_session,
        request,
        LlmRuntime(provider, max_context_chars=10_000),
    )

    db_session.expire_all()
    unchanged = db_session.get(Assessment, assessment.id)
    assert result["llm_used"] is True
    assert result["llm_status"] == "ok"
    assert result["answer"] == provider.answer
    assert str(assessment.id) in provider.user_prompt
    assert "Do not perform scheduling calculations" in provider.system_prompt
    assert unchanged.recommendation == assessment.recommendation
    assert unchanged.priority == assessment.priority
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == evidence_count
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == audit_count


@pytest.mark.parametrize("provider", [UnavailableProvider(), MalformedProvider()])
def test_llm_failure_falls_back_without_breaking_assessment(db_session, provider):
    scenario = _seed_context(db_session)
    result = service.explain_assessment(
        db_session,
        scenario["assessment"].id,
        LlmRuntime(provider, max_context_chars=10_000),
    )

    assert result["llm_used"] is False
    assert result["llm_status"] == "unavailable"
    assert result["llm_explanation"] is None
    assert result["explanation"].startswith("Assessment recommends MAINTAIN")
