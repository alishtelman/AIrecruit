from app.services.interview_service import (
    _conversational_intent_streak,
    _derive_conversational_intent,
    _is_question_repeat_candidate,
    _semantic_anti_loop_adaptation,
)


def test_conversational_intent_streak_counts_tail_repeats():
    history = ["extract_resume_case", "extract_resume_case"]
    assert _conversational_intent_streak(history, "extract_resume_case") == 3
    assert _conversational_intent_streak(history, "switch_competency_topic") == 1


def test_derive_conversational_intent_falls_back_from_action_and_phase():
    assert (
        _derive_conversational_intent(
            raw_intent="",
            action="ask_resume_followup",
            phase="resume_deep_dive",
        )
        == "extract_resume_case"
    )
    assert (
        _derive_conversational_intent(
            raw_intent="",
            action="pressure_followup",
            phase="technical_case",
        )
        == "pressure_followup_detail"
    )


def test_semantic_anti_loop_adaptation_targets_missing_resume_evidence_first():
    question, conversational_intent, information_target = _semantic_anti_loop_adaptation(
        role="qa_engineer",
        language="ru",
        current_question="Расскажите про кейс.",
        candidate_answer="кейсов много",
        competency="Bug Investigation",
        scenario_context="qa_payment_status_error",
        resume_evidence={
            "role_context": True,
            "concrete_case": True,
            "personal_actions": False,
            "result_or_impact": False,
            "resume_questions_count": 2,
        },
        answer_evaluation={"quality": "weak"},
    )

    assert "лично" in question.lower()
    assert conversational_intent == "extract_personal_actions"
    assert information_target == "personal_actions"


def test_repeat_candidate_rejects_current_question_even_if_history_lags():
    current_question = (
        "Давайте сменим компетенцию: опишите одно продуктовое решение, где вы балансировали "
        "ценность для пользователя, бизнес-эффект и риск разработки."
    )
    candidate = (
        "Опишите одно продуктовое решение, где вы балансировали ценность для пользователя, "
        "бизнес-эффект и риск разработки."
    )

    assert _is_question_repeat_candidate(
        candidate,
        previous_questions=[],
        current_question=current_question,
    )
