from app.ai.interview_intents import classify_candidate_intent
from app.ai.interview_policy import decide_interview_policy
from app.ai.pressure_followup import build_interviewer_redirect, build_pressure_followup
from app.services.interview_service import (
    _build_resume_deep_dive_followup,
    _is_forbidden_generic_question_text,
    _map_v2_action_to_legacy,
    _apply_v2_question_guardrails,
    _resume_deep_dive_can_advance,
    _resume_deep_dive_gate_opened,
    _update_resume_evidence,
)


def test_resume_gate_keeps_resume_phase_after_first_shallow_resume_answer():
    evidence = {
        "role_context": False,
        "concrete_case": False,
        "personal_actions": False,
        "result_or_impact": False,
        "resume_questions_count": 0,
    }
    evidence = _update_resume_evidence(
        resume_evidence=evidence,
        answer="Я руководитель направления сопровождения мобильного банка.",
        answer_evaluation={"has_personal_action": False, "has_result": False},
        topic_phase="intro",
    )
    assert _resume_deep_dive_gate_opened(evidence) is False
    followup = _build_resume_deep_dive_followup(
        language="ru",
        resume_evidence=evidence,
        resume_context="сопровождение мобильного банка",
    ).lower()
    assert "по вашему опыту" in followup
    assert "конкретн" in followup or "кейс" in followup


def test_product_resume_evidence_allows_stage_advance_after_concrete_pm_case():
    evidence = {
        "role_context": False,
        "concrete_case": False,
        "personal_actions": False,
        "result_or_impact": False,
        "resume_questions_count": 0,
    }
    evidence = _update_resume_evidence(
        resume_evidence=evidence,
        answer=(
            "Я продакт в финтехе. Например, в кейсе переводов я собрал данные, "
            "сформулировал гипотезу, запустил A/B эксперимент, приоритизировал "
            "доработку и конверсия выросла на 6%."
        ),
        answer_evaluation={"quality": "strong", "has_personal_action": True, "has_result": True},
        topic_phase="intro",
    )

    assert evidence["role_context"] is True
    assert evidence["concrete_case"] is True
    assert evidence["personal_actions"] is True
    assert evidence["result_or_impact"] is True
    assert _resume_deep_dive_can_advance(
        resume_evidence=evidence,
        resume_scored_turns=1,
        answer_evaluation={"quality": "strong"},
    ) is True


def test_meta_challenge_does_not_count_as_scored_answer_and_redirects():
    intent = classify_candidate_intent(
        "а ты сам ответить можешь?",
        {"current_question": "Что проверите первым в кейсе платежа?"},
    )
    assert intent["intent"] == "challenge_interviewer"
    assert intent["should_count_as_answer"] is False
    assert intent["should_advance_scenario"] is False

    policy = decide_interview_policy(
        state={"weak_answer_streak": 0, "last_step_key": "qa:1", "current_step_key": "qa:1"},
        intent_result=intent,
        answer_evaluation={"quality": "no_signal"},
    )
    assert policy["policy_action"] == "answer_meta_then_redirect"
    assert policy["count_as_scored_answer"] is False
    assert policy["advance_scenario"] is False

    reply = build_interviewer_redirect(
        intent_result=intent,
        state={},
        role="qa_engineer",
        language="ru",
        resume_context="сопровождение мобильного банка",
        current_scenario="qa_payment_status_error",
        fallback_question="Кейс: деньги списались, но статус ошибка. Что проверите первым?",
    ).lower()
    assert "ваш ход мысли" in reply or "важен" in reply
    assert "что проверите первым" in reply


def test_resume_focus_request_redirects_to_resume_context_not_scored():
    intent = classify_candidate_intent(
        "по резюме еще будут вопросы?",
        {"current_question": "Что проверите первым в кейсе платежа?"},
    )
    assert intent["intent"] in {"meta_question", "request_resume_focus"}
    assert intent["should_count_as_answer"] is False

    if intent["intent"] == "request_resume_focus":
        policy = decide_interview_policy(
            state={"weak_answer_streak": 0, "last_step_key": "qa:1", "current_step_key": "qa:1"},
            intent_result=intent,
            answer_evaluation={"quality": "no_signal"},
        )
        assert policy["policy_action"] == "resume_redirect"
        assert policy["advance_scenario"] is False


def test_weak_answer_logs_gets_pressure_followup_and_no_scenario_advance():
    intent = classify_candidate_intent(
        "логи",
        {"current_question": "Где будете искать первопричину в инциденте платежа?"},
    )
    assert intent["intent"] == "weak_answer"
    assert intent["should_count_as_answer"] is True
    assert intent["should_advance_scenario"] is False

    policy = decide_interview_policy(
        state={"weak_answer_streak": 0, "last_step_key": "qa:2", "current_step_key": "qa:2"},
        intent_result=intent,
        answer_evaluation={"quality": "weak"},
    )
    assert policy["policy_action"] == "pressure_followup"
    assert policy["advance_scenario"] is False

    followup = build_pressure_followup(
        role="qa_engineer",
        current_question="Где будете искать первопричину?",
        candidate_answer="логи",
        competency="Bug Investigation",
        scenario_context="qa_payment_status_error",
        language="ru",
    ).lower()
    assert "логи" in followup
    assert "id" in followup or "идентификатор" in followup


def test_pressure_followup_targets_missing_personal_action_result_and_forced_example():
    no_personal = build_pressure_followup(
        role="qa_engineer",
        current_question="Как вы проверяли инцидент?",
        candidate_answer="Мы проверили и подтвердили, что стало лучше.",
        competency="Bug Investigation",
        scenario_context="qa_payment_status_error",
        language="ru",
        answer_evaluation={
            "has_concrete_example": True,
            "has_personal_action": False,
            "has_result": True,
            "has_technical_detail": True,
        },
    ).lower()
    assert "лично" in no_personal

    no_result = build_pressure_followup(
        role="qa_engineer",
        current_question="Как вы проверяли инцидент?",
        candidate_answer="Я лично проверил проблему по шагам и передал фикc в разработку.",
        competency="Bug Investigation",
        scenario_context="qa_payment_status_error",
        language="ru",
        answer_evaluation={
            "has_concrete_example": True,
            "has_personal_action": True,
            "has_result": False,
            "has_technical_detail": True,
        },
    ).lower()
    assert "как вы поняли" in no_result or "подтверд" in no_result

    forced_example = build_pressure_followup(
        role="qa_engineer",
        current_question="Опишите кейс",
        candidate_answer="какой кейс?",
        competency="Bug Investigation",
        scenario_context="qa_payment_status_error",
        language="ru",
        force_concrete_example=True,
    ).lower()
    assert "деньги списались" in forced_example or "перевод" in forced_example


def test_request_example_redirect_forces_concrete_case():
    intent = classify_candidate_intent(
        "какой кейс?",
        {"current_question": "Разберите кейс"},
    )
    redirected = build_interviewer_redirect(
        intent_result=intent,
        state={},
        role="qa_engineer",
        language="ru",
        resume_context="",
        current_scenario=None,
        fallback_question="Уточните кейс",
    ).lower()
    assert "на конкретном примере" in redirected
    assert ("деньги списались" in redirected) or ("перевод" in redirected)


def test_resume_debug_sequence_holds_phase_and_stays_in_resume_without_technical_case():
    role = "qa_engineer"
    language = "ru"
    state_v2 = {
        "phase": "resume_deep_dive",
        "confusion_count": 0,
        "repeated_question_count": 0,
    }
    resume_evidence = {
        "role_context": False,
        "concrete_case": False,
        "personal_actions": False,
        "result_or_impact": False,
        "resume_questions_count": 0,
    }
    asked_questions: list[str] = []
    transcript_summary: list[str] = []
    scenarios = []

    messages = [
        "Алишер, 28 лет, рук направления сопровождения bcc.kz",
        "А в чем вопрос?",
        "какой кейс?",
        "не понял тебя",
    ]
    current_question = "Расскажите о вашем опыте по QA."
    produced_questions: list[str] = []
    current_phase = "resume_deep_dive"

    for message in messages:
        intent = classify_candidate_intent(message, {"current_question": current_question})
        should_count = bool(intent.get("should_count_as_answer", True))
        evaluation = {
            "quality": "no_signal",
            "has_personal_action": False,
            "has_result": False,
            "has_concrete_example": False,
            "has_technical_detail": False,
        }
        if should_count:
            evaluation["quality"] = "weak"
        policy = decide_interview_policy(
            state={"weak_answer_streak": 0, "last_step_key": "resume:0", "current_step_key": "resume:0"},
            intent_result=intent,
            answer_evaluation=evaluation,
        )
        if bool(policy.get("update_confusion_count")):
            state_v2["confusion_count"] = int(state_v2.get("confusion_count", 0)) + 1

        resume_evidence = _update_resume_evidence(
            resume_evidence=resume_evidence,
            answer=message,
            answer_evaluation=evaluation,
            topic_phase="resume_followup",
        )

        gate_opened = _resume_deep_dive_gate_opened(resume_evidence)
        if not gate_opened:
            next_question = _build_resume_deep_dive_followup(
                language=language,
                resume_evidence=resume_evidence,
                resume_context="сопровождение мобильного банка",
            )
            action = "follow_up"
        elif policy["policy_action"] in {"clarify", "answer_meta_then_redirect", "resume_redirect", "give_example_scenario"}:
            next_question = build_interviewer_redirect(
                intent_result=intent,
                state=state_v2,
                role=role,
                language=language,
                resume_context="сопровождение мобильного банка",
                current_scenario=None,
                fallback_question="Кейс: платеж не прошел, но деньги списались. Что проверите первым?",
            )
            action = "simplify"
        else:
            next_question = "Разберите один другой кейс: контекст, ваши действия и измеримый результат?"
            action = "ask_new_topic"

        raw = {
            "action": action,
            "question_text": next_question,
            "reason": "test",
            "target_competency": "Bug Investigation",
            "difficulty": 3,
            "question_type": _map_v2_action_to_legacy(action)[0],
            "will_advance": _map_v2_action_to_legacy(action)[1],
            "selected_topic_index": None,
            "scenario_case_id": None,
            "scenario_step_index": 0,
        }
        guarded = _apply_v2_question_guardrails(
            question_decision=raw,
            role=role,
            language=language,
            asked_question_texts=asked_questions,
            transcript_summary=transcript_summary,
            current_competency="Bug Investigation",
            scenario_chains=scenarios,
            state_v2_before=state_v2,
            active_qa_scenario_id=None,
            active_qa_scenario_step=0,
        )
        current_question = str(guarded.get("question_text") or "")
        produced_questions.append(current_question)
        asked_questions.append(current_question)
        transcript_summary.append(current_question)

        if not gate_opened:
            current_phase = "resume_deep_dive"

    assert current_phase == "resume_deep_dive"
    assert all(not _is_forbidden_generic_question_text(q) for q in produced_questions)
    assert any(("по вашему опыту" in q.lower()) or ("переформулирую" in q.lower()) for q in produced_questions)
    assert all("платеж" not in q.lower() for q in produced_questions)
    assert all("endpoint" not in q.lower() for q in produced_questions)
    assert all("api" not in q.lower() for q in produced_questions)
