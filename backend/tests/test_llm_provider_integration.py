import pytest

from app.ai.interview_strategist import (
    InterviewStrategistContext,
    LLMInterviewStrategist,
)
from app.ai.providers.base import LLMProvider, ProviderChatError
from app.ai.providers.factory import get_llm_provider
from app.ai.interview_strategist import QuestionDecision
from app.core.config import Settings
from app.services.interview_service import _select_next_question_decision_v2


def test_provider_factory_selects_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("APP_ENV", "development")

    provider = get_llm_provider(Settings())

    assert provider.name == "openai"
    assert provider.configured_model == "gpt-5.4-mini"


class _AlwaysFailProvider(LLMProvider):
    name = "openai"

    @property
    def configured_model(self) -> str:
        return "gpt-5.4-mini"

    @property
    def is_configured(self) -> bool:
        return True

    async def chat_completion(
        self,
        *,
        messages,
        model,
        temperature,
        max_tokens,
        response_format=None,
        extra_body=None,
        timeout=None,
    ):
        _ = (messages, model, temperature, max_tokens, response_format, extra_body, timeout)
        raise ProviderChatError("provider unavailable", code="all_models_failed")


@pytest.mark.asyncio
async def test_openai_unavailable_propagates_exception_explicitly():
    strategist = LLMInterviewStrategist(provider=_AlwaysFailProvider())
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=[],
        available_scenarios=[
            {
                "case_id": "qa_case_1",
                "title": "Платеж: деньги списались, статус ошибка",
                "competency": "Bug Investigation",
                "questions": [
                    "Кейс: платеж не прошел, но деньги списались. Что проверите первым?",
                    "Какие данные соберете в первую очередь?",
                ],
            }
        ],
    )

    with pytest.raises(ProviderChatError) as exc_info:
        await strategist.decide_next_interview_action(ctx)

    assert "provider unavailable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_v2_question_decision_exposes_provider_error_fields(monkeypatch: pytest.MonkeyPatch):
    async def _fake_decide(_ctx):
        return QuestionDecision(
            action="clarify",
            question_text="Давайте на примере: клиент сообщает об ошибке платежа. Что проверите первым?",
            target_competency="Bug Investigation",
            phase="resume_deep_dive",
            scenario_id="qa_case_1",
            scenario_step=0,
            difficulty_tier=2,
            reason="test_provider_trace",
            expected_signal="concrete_steps",
            ai_provider="openai",
            requested_model="gpt-5.4-mini",
            actual_model_used="gpt-5.4-mini",
            provider_attempts=[
                {"model": "gpt-5.4-mini", "ok": False, "error": "429 rate_limit"},
                {"model": "gpt-5.4-mini", "ok": True, "error": None},
            ],
            provider_errors=["gpt-5.4-mini: 429 rate_limit"],
            provider_fallback_used=True,
        )

    monkeypatch.setattr("app.services.interview_service.decide_next_interview_action", _fake_decide)

    result = await _select_next_question_decision_v2(
        role="qa_engineer",
        language="ru",
        resume_summary="",
        role_competency_map=["Bug Investigation"],
        interview_state_v2={"phase": "resume_deep_dive"},
        last_question="",
        last_answer="не понял",
        last_answer_evaluation={"quality": "no_signal"},
        transcript_summary=[],
        asked_questions=[],
        available_scenarios=[],
        policy_action="clarify",
        candidate_intent="clarification_request",
        missing_signal="Bug Investigation",
        pressure_goal="collect_concrete_example",
        reasoning_hints={},
        model_preference=None,
    )

    assert result["ai_provider"] == "openai"
    assert result["requested_model"] == "gpt-5.4-mini"
    assert result["actual_model_used"] == "gpt-5.4-mini"
    assert result["provider_fallback_used"] is True
    assert len(result["provider_attempts"]) == 2
    assert result["provider_errors"]
