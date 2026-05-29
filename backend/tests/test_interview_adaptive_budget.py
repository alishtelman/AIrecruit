import asyncio

from app.services.interview_service import (
    _apply_low_confidence_verdict_guard,
    _compute_scoring_v2_evidence,
    _append_candidate_memory,
    _derive_adaptive_difficulty_tier,
    _derive_proficiency_profile,
    _estimate_dynamic_question_budget,
    _is_clarification_request,
    _is_move_on_request,
    _is_noise_or_nonsense_answer,
    _is_question_already_covered_in_transcript,
    _is_structured_phase_plan,
    _next_report_diagnostics,
    _qa_case_questions_asked_count,
    _qa_technical_signal_percent,
    _rebuild_topic_plan_with_max_questions,
    _read_report_diagnostics,
    _find_next_unasked_technical_topic_index,
    
    _resolve_next_topic_index,
    _topic_signature_key,
    classify_candidate_intent_v2,
    evaluate_answer_runtime_v2,
)
from app.ai.interviewer import InterviewContext
from app.ai.competencies import build_interview_plan
from app.ai.assessor import AssessmentResult
from app.services import interview_service

import pytest


def test_evaluate_answer_runtime_v2_treats_clarification_as_no_signal_not_weak():
    evaluation = evaluate_answer_runtime_v2(
        question="Разберите технический кейс по API/данным: как проектировали, что проверяли, где были trade-off?",
        answer="Не понял, какой кейс?",
        transcript=[],
        role="qa_engineer",
    )

    assert evaluation["quality"] == "no_signal"
    assert evaluation["candidate_asks_clarification"] is True
    assert evaluation["candidate_confusion"] is True
    assert evaluation["recommended_next_action"] == "simplify"
    assert evaluation["followup_type"] == "simplify"
    assert evaluation["candidate_intent"]["intent"] == "clarification_request"
    assert evaluation["candidate_intent"]["should_count_as_answer"] is False
    assert evaluation["candidate_intent"]["should_advance_scenario"] is False


def test_classify_candidate_intent_v2_meta_and_resume_personalization():
    meta = classify_candidate_intent_v2("а ты сам ответить можешь?")
    assert meta["intent"] == "meta_question"
    assert meta["should_count_as_answer"] is False
    assert meta["should_advance_scenario"] is False

    personalize = classify_candidate_intent_v2("давай по моему опыту, по моей работе еще вопросы будут?")
    assert personalize["intent"] == "request_personalized_to_resume"
    assert personalize["should_count_as_answer"] is False
    assert personalize["should_advance_scenario"] is False


def test_evaluate_answer_runtime_v2_marks_refusal_as_weak_signal_without_advancing():
    evaluation = evaluate_answer_runtime_v2(
        question="Где будете искать первопричину?",
        answer="не знаю",
        transcript=[],
        role="qa_engineer",
    )

    assert evaluation["candidate_intent"]["intent"] == "dont_know"
    assert evaluation["candidate_intent"]["should_count_as_answer"] is True
    assert evaluation["candidate_intent"]["should_advance_scenario"] is False
    assert evaluation["quality"] == "weak"
    assert evaluation["recommended_next_action"] == "follow_up"
    assert evaluation["pressure_followup_required"] is True


def test_evaluate_answer_runtime_v2_flags_general_weak_answer_for_pressure_followup():
    evaluation = evaluate_answer_runtime_v2(
        question="Где будете искать первопричину?",
        answer="везде",
        transcript=[],
        role="qa_engineer",
    )

    assert evaluation["quality"] in {"weak", "no_signal"}
    assert evaluation["pressure_followup_required"] is True


def test_evaluate_answer_runtime_v2_marks_short_blurry_answer_as_weak():
    evaluation = evaluate_answer_runtime_v2(
        question="Как проверяли фикс в релизе?",
        answer="Ну обычно по ситуации, как обычно.",
        transcript=[],
        role="qa_engineer",
    )

    assert evaluation["quality"] == "weak"
    assert evaluation["evidence_type"] in {"generic", "none"}
    assert evaluation["recommended_next_action"] == "follow_up"


def test_evaluate_answer_runtime_v2_marks_full_evidence_answer_as_strong():
    evaluation = evaluate_answer_runtime_v2(
        question="Как проверяли дефект со списанием денег и ошибочным статусом?",
        answer=(
            "Например, в прошлом релизе я лично воспроизвел кейс через API endpoint /payments, "
            "собрал request_id и логи, проверил SQL-запросы и статус в БД, "
            "с разработчиком выбрали компромисс между скоростью фикса и безопасностью отката, "
            "после фикса p95 снизили на 18% и ошибка списания больше не воспроизводилась."
        ),
        transcript=[],
        role="qa_engineer",
    )

    assert evaluation["quality"] == "strong"
    assert evaluation["has_concrete_example"] is True
    assert evaluation["has_personal_action"] is True
    assert evaluation["has_technical_detail"] is True
    assert evaluation["has_result"] is True
    assert evaluation["evidence_type"] == "measurable_result"
    assert evaluation["recommended_next_action"] in {"switch_topic", "continue_scenario"}




def test_derive_adaptive_difficulty_tier_increases_on_strong_streak():
    tier = _derive_adaptive_difficulty_tier(
        current_tier=3,
        answer_class="strong",
        answer_relevance="high",
        strong_answers_count=4,
        weak_answers_count=1,
        consecutive_strong_answers=2,
        consecutive_weak_answers=0,
    )

    assert tier == 5


def test_derive_adaptive_difficulty_tier_decreases_on_weak_streak():
    tier = _derive_adaptive_difficulty_tier(
        current_tier=4,
        answer_class="generic",
        answer_relevance="low",
        strong_answers_count=1,
        weak_answers_count=4,
        consecutive_strong_answers=0,
        consecutive_weak_answers=2,
    )

    assert tier == 1





def test_noise_or_nonsense_answer_detects_repetitive_input():
    assert _is_noise_or_nonsense_answer("ну ну ну ну ну ну ну ну")
    assert _is_noise_or_nonsense_answer("asdf asdf asdf asdf asdf asdf")
    assert not _is_noise_or_nonsense_answer(
        "Я использовал PostgreSQL в production и оптимизировал индексы под реальную нагрузку."
    )

def test_clarification_request_detection_handles_short_reask_variants():
    assert _is_clarification_request("не понял")
    assert _is_clarification_request("что именно имеете в виду?")
    assert _is_clarification_request("кого?")
    assert _is_clarification_request("could you clarify?")
    assert not _is_clarification_request("Я использовал PostgreSQL и оптимизировал запросы.")


def test_move_on_request_detection_handles_already_answered_signal():
    assert _is_move_on_request("На это уже отвечал, давайте дальше")
    assert _is_move_on_request("Я уже писал выше, давайте следующий вопрос")
    assert _is_move_on_request("I already answered this, next question")
    assert not _is_move_on_request("Давайте разберем это подробнее по шагам")


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


def test_estimate_dynamic_question_budget_respects_selected_seniority_caps():
    rich_profile = {
        "technologies": ["figma", "framer", "react", "graphql"],
        "project_highlights": ["product redesign", "design system revamp", "a/b experiment rollout"],
        "experience_years": 5,
        "seniority_hint": "senior",
    }

    junior_initial, junior_cap, _ = _estimate_dynamic_question_budget(
        target_role="designer",
        resume_profile=rich_profile,
        selected_seniority="junior",
    )
    middle_initial, middle_cap, _ = _estimate_dynamic_question_budget(
        target_role="designer",
        resume_profile=rich_profile,
        selected_seniority="middle",
    )
    senior_initial, senior_cap, _ = _estimate_dynamic_question_budget(
        target_role="designer",
        resume_profile=rich_profile,
        selected_seniority="senior",
    )

    assert junior_cap == 16
    assert middle_cap == 24
    assert senior_cap == 30
    assert junior_initial <= middle_initial <= senior_initial


def test_build_interview_plan_for_qa_has_competency_specific_case_leads():
    plan = build_interview_plan(
        "qa_engineer",
        10,
        {"project_highlights": ["Мониторинг релизов"], "verification_targets": ["postgresql"]},
        structured_flow=True,
    )

    technical_slots = [slot for slot in plan if slot.get("phase") == "technical"]
    assert len(technical_slots) >= 6
    lead_questions = [str(slot.get("lead_question") or "") for slot in technical_slots[:6]]

    assert any("smoke" in question.lower() for question in lead_questions)
    assert any("api" in question.lower() for question in lead_questions)
    assert any("production-дефект" in question.lower() or "production" in question.lower() for question in lead_questions)


def test_question_covered_in_transcript_detects_semantic_overlap():
    question = "Один API-кейс: какой endpoint проверяли и какие негативные сценарии добавили?"
    summary = [
        "technical_foundation: Проверял endpoint /payments, добавлял негативные сценарии на невалидный токен и пустой payload.",
    ]

    assert _is_question_already_covered_in_transcript(question, summary) is True


def test_low_confidence_verdict_guard_forces_maybe():
    result = AssessmentResult(
        overall_score=6.4,
        hard_skills_score=6.2,
        soft_skills_score=6.0,
        communication_score=6.1,
        problem_solving_score=6.0,
        strengths=["Strong ownership"],
        weaknesses=["Low evidence depth"],
        recommendations=["Add more concrete examples"],
        hiring_recommendation="no",
        interview_summary="Limited signal quality.",
        model_version="test",
        full_report_json={},
        overall_confidence=0.18,
    )

    guarded = _apply_low_confidence_verdict_guard(result)
    reasons = list(guarded.full_report_json.get("recommendation_gate_reasons") or [])

    assert guarded.hiring_recommendation == "maybe"
    assert any("below 40%" in reason for reason in reasons)


def test_estimate_dynamic_question_budget_keeps_legacy_sparse_resume_behavior():
    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="backend_engineer",
        resume_profile={},
    )

    assert initial == 8
    assert cap == 8
    assert min_questions == 9


def test_estimate_dynamic_question_budget_keeps_qa_floor_even_for_sparse_resume():
    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="qa_engineer",
        resume_profile={},
    )

    assert initial >= 10
    assert cap >= initial
    assert min_questions >= 10


def test_estimate_dynamic_question_budget_qa_v2_role_window(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "v2")
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_V2_ROLES", "qa_engineer")

    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="qa_engineer",
        resume_profile={
            "technologies": ["python", "postgresql", "kafka", "redis"],
            "project_highlights": ["payments", "regression", "ci"],
            "experience_years": 8,
            "seniority_hint": "senior",
        },
    )

    assert initial == 10
    assert cap == 10
    assert min_questions == 10


def test_qa_case_questions_and_signal_use_only_asked_case_topics():
    topic_plan = build_interview_plan(
        "qa_engineer",
        10,
        {"project_highlights": [], "verification_targets": []},
        structured_flow=True,
    )
    asked = [_topic_signature_key(topic_plan[idx]) for idx in [0, 1, 2, 3, 4, 5]]
    topic_signals = ["strong", "strong", "partial", "partial", "strong", "generic"]

    case_count = _qa_case_questions_asked_count(topic_plan, asked)
    signal_pct = _qa_technical_signal_percent(topic_plan, topic_signals, asked)

    assert case_count >= 5
    assert 0.0 <= signal_pct <= 100.0
    assert signal_pct < 80.0


def test_find_next_unasked_technical_topic_index_skips_behavioral_slot():
    topic_plan = build_interview_plan(
        "qa_engineer",
        10,
        {"project_highlights": [], "verification_targets": []},
        structured_flow=True,
    )
    asked = [_topic_signature_key(topic_plan[idx]) for idx in [0, 1, 2, 3]]

    idx = _find_next_unasked_technical_topic_index(
        topic_plan,
        asked_topics=asked,
        topic_signals=["strong", "partial", "partial", "strong"],
    )

    assert idx is not None
    assert topic_plan[idx]["phase"] != "behavioral_closing"





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


def test_rebuild_topic_plan_with_max_questions_keeps_behavioral_closing_last():
    topic_plan = [
        {"phase": "intro", "competencies": ["Communication"]},
        {"phase": "resume_followup", "competencies": ["Communication"]},
        {"phase": "technical", "competencies": ["API Design & Protocols"]},
        {"phase": "behavioral_closing", "competencies": ["Ownership & Growth Mindset"]},
    ]

    rebuilt = _rebuild_topic_plan_with_max_questions(
        topic_plan=topic_plan,
        target_role="backend_engineer",
        resume_profile={"project_highlights": ["billing service"]},
        max_questions=8,
    )

    assert len(rebuilt) == 8
    assert rebuilt[0]["phase"] == "intro"
    assert rebuilt[1]["phase"] == "resume_followup"
    assert rebuilt[-1]["phase"] == "behavioral_closing"
    assert all(item["phase"] != "behavioral_closing" for item in rebuilt[:-1])


def test_rebuild_topic_plan_with_max_questions_preserves_role_order_start():
    topic_plan = [
        {"phase": "intro", "competencies": ["Technical Communication"]},
        {"phase": "resume_followup", "competencies": ["API Design & Protocols"]},
        {"phase": "technical", "competencies": ["Database Design & Optimization"]},
        {"phase": "behavioral_closing", "competencies": ["Ownership & Growth Mindset"]},
    ]

    rebuilt = _rebuild_topic_plan_with_max_questions(
        topic_plan=topic_plan,
        target_role="backend_engineer",
        resume_profile={"project_highlights": ["billing service"]},
        max_questions=10,
    )

    assert rebuilt[1]["competencies"][0] == "API Design & Protocols"
    assert rebuilt[2]["competencies"][0] == "Database Design & Optimization"
    assert rebuilt[-1]["phase"] == "behavioral_closing"




def test_is_structured_phase_plan_detects_presence_of_phases():
    assert _is_structured_phase_plan([{"phase": "intro"}, {"phase": "technical"}]) is True
    assert _is_structured_phase_plan([{"competencies": ["X"]}, {"phase": ""}]) is False


def test_next_report_diagnostics_increments_attempts_and_tracks_errors():
    first = _next_report_diagnostics(
        None,
        phase="finish_sync",
        status="processing",
    )
    second = _next_report_diagnostics(
        first,
        phase="async_worker",
        status="failed",
        error="provider timeout",
    )

    assert first["attempt_count"] == 1
    assert second["attempt_count"] == 1
    assert second["last_phase"] == "async_worker"
    assert second["last_status"] == "failed"
    assert second["last_error"] == "provider timeout"
    assert second["last_error_at"] is not None


def test_proficiency_profile_uses_15_level_junior_middle_senior_ladder():
    profile = _derive_proficiency_profile(
        overall_score=6.8,
        hard_skills_score=6.7,
        problem_solving_score=6.5,
        communication_score=6.0,
        overall_confidence=0.72,
        language="ru",
    )

    assert profile["proficiency_level"] == 10.0
    assert profile["proficiency_band"] == "middle_5"
    assert profile["proficiency_label"] == "Middle 5"
    assert profile["sfia_band"] == "sfia_5"


def test_proficiency_profile_applies_high_senior_gate_when_core_signals_are_weak():
    profile = _derive_proficiency_profile(
        overall_score=9.8,
        hard_skills_score=6.2,
        problem_solving_score=6.1,
        communication_score=5.2,
        overall_confidence=0.92,
        language="en",
    )

    assert profile["proficiency_level"] == 13.0
    assert profile["proficiency_band"] == "senior_3"
    assert profile["proficiency_label"] == "Senior 3"


def test_proficiency_profile_applies_positive_trajectory_adjustment():
    profile = _derive_proficiency_profile(
        overall_score=7.8,
        hard_skills_score=7.1,
        problem_solving_score=7.0,
        communication_score=6.2,
        overall_confidence=0.76,
        language="ru",
        interview_meta={
            "candidate_answers_count": 10,
            "strong_answers_count": 6,
            "weak_answers_count": 2,
            "consecutive_weak_answers": 0,
            "adaptive_difficulty_tier": 5,
        },
    )

    assert profile["proficiency_level"] == 12.0
    assert profile["proficiency_band"] == "senior_2"
    assert profile["trajectory_adjustment"] == 1


def test_proficiency_profile_applies_negative_trajectory_adjustment():
    profile = _derive_proficiency_profile(
        overall_score=6.2,
        hard_skills_score=6.1,
        problem_solving_score=6.0,
        communication_score=5.7,
        overall_confidence=0.7,
        language="en",
        interview_meta={
            "candidate_answers_count": 8,
            "strong_answers_count": 1,
            "weak_answers_count": 5,
            "consecutive_weak_answers": 3,
            "adaptive_difficulty_tier": 2,
        },
    )

    assert profile["proficiency_level"] == 8.0
    assert profile["proficiency_band"] == "middle_3"
    assert profile["trajectory_adjustment"] == -1


def test_proficiency_profile_v2_caps_middle_when_validated_competencies_below_three():
    profile = _derive_proficiency_profile(
        target_role="qa_engineer",
        overall_score=7.6,
        hard_skills_score=7.2,
        problem_solving_score=7.0,
        communication_score=6.8,
        overall_confidence=0.82,
        language="ru",
        validated_competencies_count=2,
        has_completed_scenario_with_strong_evidence=True,
        has_strategy_ownership_evidence=True,
    )

    assert profile["proficiency_level"] <= 5.0
    assert "middle_requires_3_validated_competencies" in profile["gate_reasons"]


def test_proficiency_profile_v2_requires_completed_scenario_for_strong_middle():
    profile = _derive_proficiency_profile(
        target_role="qa_engineer",
        overall_score=8.4,
        hard_skills_score=8.1,
        problem_solving_score=8.0,
        communication_score=7.2,
        overall_confidence=0.86,
        language="en",
        validated_competencies_count=4,
        has_completed_scenario_with_strong_evidence=False,
        has_strategy_ownership_evidence=False,
    )

    assert profile["proficiency_level"] <= 8.0
    assert "strong_middle_requires_completed_scenario_with_strong_evidence" in profile["gate_reasons"]


def test_proficiency_profile_v2_requires_strategy_signal_for_senior():
    profile = _derive_proficiency_profile(
        target_role="backend_engineer",
        overall_score=9.3,
        hard_skills_score=8.8,
        problem_solving_score=8.7,
        communication_score=7.4,
        overall_confidence=0.9,
        language="en",
        validated_competencies_count=6,
        has_completed_scenario_with_strong_evidence=True,
        has_strategy_ownership_evidence=False,
    )

    assert profile["proficiency_level"] <= 10.0
    assert "senior_requires_strategy_or_system_ownership_evidence" in profile["gate_reasons"]


def test_scoring_v2_evidence_ignores_non_role_competency_resume_tech_for_qa():
    evidence = _compute_scoring_v2_evidence(
        target_role="qa_engineer",
        competency_scores=[
            {
                "competency": "PostgreSQL",
                "score": 9.1,
                "weight": 0.1,
                "evidence": "Candidate mentioned PostgreSQL in resume.",
            },
            {
                "competency": "Test Strategy & Planning",
                "score": 7.2,
                "weight": 0.2,
                "evidence": "Concrete QA planning case with prioritization and risks.",
            },
        ],
        competency_confidence={"PostgreSQL": 0.9, "Test Strategy & Planning": 0.7},
        per_question_analysis=[
            {
                "targeted_competencies": ["Test Strategy & Planning"],
                "answer_quality": 7.5,
                "depth": "strong",
                "evidence": "Defined release risk matrix and focused regression around payment scenarios.",
            }
        ],
        interview_meta={"qa_completed_scenarios": ["qa_payment_status_error"]},
        evidence_coverage={"strong_answers_count": 1, "case_depth_ratio": 0.72},
    )

    assert "PostgreSQL" not in evidence["validated_competencies"]
    assert "Test Strategy & Planning" in evidence["validated_competencies"]


def test_read_report_diagnostics_sanitizes_unknown_status():
    class _InterviewStub:
        def __init__(self, state):
            self.interview_state = state

    diagnostics = _read_report_diagnostics(
        _InterviewStub(
            {
                "report_diagnostics": {
                    "attempt_count": "2",
                    "last_status": "unknown_status",
                    "last_error": "boom",
                }
            }
        )
    )

    assert diagnostics is not None
    assert diagnostics["attempt_count"] == 2
    assert diagnostics["last_status"] is None
    assert diagnostics["last_error"] == "boom"



