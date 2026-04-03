from app.services.interview_service import (
    _assess_with_dev_fallback,
    _get_next_question_with_dev_fallback,
    _adapt_question_budget,
    _append_candidate_memory,
    _estimate_dynamic_question_budget,
    _resolve_next_topic_index,
    _topic_guard_decision,
)
from app.ai.interviewer import InterviewContext

import pytest


def test_adapt_question_budget_extends_for_strong_signal_near_limit():
    adapted, should_end, decision = _adapt_question_budget(
        current_max_questions=14,
        current_question_count=12,
        answer_count=5,
        strong_answers_count=3,
        weak_answers_count=1,
        low_relevance_answers_count=1,
        consecutive_weak_answers=0,
        min_questions_before_early_stop=10,
        role_max_cap=24,
    )

    assert adapted == 18
    assert should_end is False
    assert decision == "extended_for_strong_signal"


def test_adapt_question_budget_reduces_early_for_mixed_low_signal():
    adapted, should_end, decision = _adapt_question_budget(
        current_max_questions=24,
        current_question_count=7,
        answer_count=5,
        strong_answers_count=0,
        weak_answers_count=4,
        low_relevance_answers_count=2,
        consecutive_weak_answers=2,
        min_questions_before_early_stop=10,
        role_max_cap=40,
    )

    assert adapted == 10
    assert should_end is False
    assert decision == "reduced_for_mixed_low_signal"


def test_append_candidate_memory_keeps_honest_short_gap():
    memory = _append_candidate_memory(
        [],
        answer="Не делал интеграцию с Kubernetes и не настраивал её в production.",
        answer_class="no_experience_honest",
        answer_relevance="low",
        new_techs=set(),
    )

    assert len(memory) == 1
    assert memory[0].lower().startswith("honest gap noted:")


def test_append_candidate_memory_deduplicates_similar_facts():
    answer = (
        "Я использовал PostgreSQL в production, анализировал EXPLAIN ANALYZE, "
        "оптимизировал индексы и снизил latency на горячих запросах."
    )
    first = _append_candidate_memory(
        [],
        answer=answer,
        answer_class="strong",
        answer_relevance="high",
        new_techs={"postgresql"},
    )
    second = _append_candidate_memory(
        first,
        answer=answer,
        answer_class="strong",
        answer_relevance="high",
        new_techs={"postgresql"},
    )

    assert len(second) == 1
    assert "[tech: postgresql]" in second[0].lower()


def test_estimate_dynamic_question_budget_uses_role_floor_for_rich_resume():
    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="designer",
        resume_profile={
            "technologies": ["figma", "framer"],
            "project_highlights": ["product redesign"],
            "experience_years": 2,
            "seniority_hint": "middle",
        },
    )

    assert initial >= 8
    assert cap == 30
    assert min_questions == 8


def test_estimate_dynamic_question_budget_keeps_legacy_sparse_resume_behavior():
    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="backend_engineer",
        resume_profile={},
    )

    assert initial == 8
    assert cap == 8
    assert min_questions == 9


def test_topic_guard_requires_claim_probe_before_advancing():
    must_probe, closure_reason = _topic_guard_decision(
        claim_target="postgresql",
        verified_skills=set(),
        probed_claim_targets=set(),
        can_probe_current_topic=True,
    )

    assert must_probe is True
    assert closure_reason is None


def test_topic_guard_closes_unverified_claim_when_probe_window_is_exhausted():
    must_probe, closure_reason = _topic_guard_decision(
        claim_target="postgresql",
        verified_skills=set(),
        probed_claim_targets={"postgresql"},
        can_probe_current_topic=False,
    )

    assert must_probe is False
    assert closure_reason == "claim_unverified_after_probe"


def test_resolve_next_topic_index_skips_similar_signature_for_claim_unverified_closure():
    topic_plan = [
        {"verification_target": "postgresql", "competencies": ["Database Design & Optimization"]},
        {"verification_target": "postgresql", "competencies": ["Database Design & Optimization"]},
        {"verification_target": "kafka", "competencies": ["API Design & Protocols"]},
    ]

    resolved = _resolve_next_topic_index(
        topic_plan=topic_plan,
        current_topic_index=0,
        default_next_index=1,
        close_reason="claim_unverified_after_probe",
    )

    assert resolved == 2


class _FailingInterviewer:
    async def get_next_question(self, _ctx: InterviewContext) -> str:
        raise RuntimeError("provider failed")


class _FallbackInterviewer:
    async def get_next_question(self, _ctx: InterviewContext) -> str:
        return "Fallback question?"


@pytest.mark.asyncio
async def test_get_next_question_with_dev_fallback_uses_mock_in_local_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services import interview_service as interview_service_module

    monkeypatch.setattr(interview_service_module, "interviewer", _FailingInterviewer())
    monkeypatch.setattr(interview_service_module, "MockInterviewer", _FallbackInterviewer)
    monkeypatch.setattr(interview_service_module.settings, "APP_ENV", "development")

    question = await _get_next_question_with_dev_fallback(
        InterviewContext(target_role="backend_engineer", question_number=1, language="ru")
    )

    assert question == "Fallback question?"


@pytest.mark.asyncio
async def test_get_next_question_with_dev_fallback_raises_in_production_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services import interview_service as interview_service_module

    monkeypatch.setattr(interview_service_module, "interviewer", _FailingInterviewer())
    monkeypatch.setattr(interview_service_module.settings, "APP_ENV", "production")

    with pytest.raises(RuntimeError, match="AI interviewer request failed"):
        await _get_next_question_with_dev_fallback(
            InterviewContext(target_role="backend_engineer", question_number=1, language="ru")
        )


class _FailingAssessor:
    async def assess(self, **_kwargs):
        raise RuntimeError("assessor provider failed")


@pytest.mark.asyncio
async def test_assess_with_dev_fallback_uses_mock_in_local_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services import interview_service as interview_service_module

    monkeypatch.setattr(interview_service_module, "assessor", _FailingAssessor())
    monkeypatch.setattr(interview_service_module.settings, "APP_ENV", "development")

    result = await _assess_with_dev_fallback(
        target_role="backend_engineer",
        message_history=[
            {"role": "assistant", "content": "Расскажите о своем опыте с PostgreSQL."},
            {"role": "candidate", "content": "Я использовал PostgreSQL и оптимизировал индексы."},
        ],
        message_timestamps=None,
        behavioral_signals=None,
        language="ru",
        interview_meta={},
    )

    assert result.hiring_recommendation in {"no", "maybe", "yes", "strong_yes"}


@pytest.mark.asyncio
async def test_assess_with_dev_fallback_raises_in_production_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services import interview_service as interview_service_module

    monkeypatch.setattr(interview_service_module, "assessor", _FailingAssessor())
    monkeypatch.setattr(interview_service_module.settings, "APP_ENV", "production")

    with pytest.raises(RuntimeError, match="AI assessor request failed"):
        await _assess_with_dev_fallback(
            target_role="backend_engineer",
            message_history=[],
            message_timestamps=None,
            behavioral_signals=None,
            language="ru",
            interview_meta={},
        )
