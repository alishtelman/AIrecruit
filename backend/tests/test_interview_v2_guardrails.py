from app.services.interview_service import (
    _apply_v2_question_guardrails,
    _is_generic_question_text_without_context,
)


def test_generic_question_guardrail_flags_ambiguous_case_prompt():
    assert _is_generic_question_text_without_context("Разберите кейс и расскажите подробнее?")
    assert not _is_generic_question_text_without_context(
        "Представьте: пользователь сделал перевод, деньги списались, но статус ошибки. Что проверите первым?"
    )


def test_v2_guardrail_repeated_question_flags_without_forcing_scenario():
    decision = {
        "action": "ask_new_topic",
        "question_text": "Разберите кейс и расскажите подробнее?",
        "reason": "v2_strategist",
        "target_competency": "Bug Investigation",
        "difficulty": 3,
        "question_type": "main",
        "will_advance": True,
        "selected_topic_index": None,
    }
    adjusted = _apply_v2_question_guardrails(
        question_decision=decision,
        role="qa_engineer",
        language="ru",
        asked_question_texts=["Разберите кейс и расскажите подробнее?"],
        transcript_summary=[],
        current_competency="Bug Investigation",
        scenario_chains=[
            {
                "case_id": "qa_payment",
                "competency": "Bug Investigation",
                "difficulty_tier": 3,
                "questions": [
                    "Q1: Как воспроизведете дефект?",
                    "Q2: Какие данные соберете: request id, response, логи, БД?",
                ],
            }
        ],
        state_v2_before={"confusion_count": 0, "repeated_question_count": 0},
        active_qa_scenario_id=None,
        active_qa_scenario_step=0,
    )

    assert adjusted["action"] == "ask_new_topic"
    assert adjusted["question_repeated_guardrail_triggered"] is True
    assert adjusted["guardrail_reason"] in {
        "repeated_question_rejected",
        "generic_question_without_context_rejected",
    }


def test_v2_guardrail_does_not_force_scenario_when_confusion_count_high():
    decision = {
        "action": "ask_new_topic",
        "question_text": "Опишите ваш подход к тестированию?",
        "reason": "v2_strategist",
        "target_competency": "Test Strategy & Planning",
        "difficulty": 3,
        "question_type": "main",
        "will_advance": True,
        "selected_topic_index": None,
    }
    adjusted = _apply_v2_question_guardrails(
        question_decision=decision,
        role="qa_engineer",
        language="ru",
        asked_question_texts=[],
        transcript_summary=[],
        current_competency="Test Strategy & Planning",
        scenario_chains=[
            {
                "case_id": "qa_release_fee",
                "competency": "Regression Risk",
                "difficulty_tier": 3,
                "questions": [
                    "Представьте: релиз завтра, изменилась комиссия. Какие проверки возьмете в первую очередь?",
                ],
            }
        ],
        state_v2_before={"confusion_count": 2, "repeated_question_count": 0},
        active_qa_scenario_id=None,
        active_qa_scenario_step=0,
    )

    assert adjusted["action"] == "ask_new_topic"
    assert adjusted.get("guardrail_reason") is None
