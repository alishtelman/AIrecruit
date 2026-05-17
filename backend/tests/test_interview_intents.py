from app.ai.interview_intents import classify_candidate_intent


def _ctx(question: str = "Где будете искать первопричину в кейсе платежа?") -> dict:
    return {
        "role": "qa_engineer",
        "phase": "technical_case",
        "current_question": question,
        "transcript_summary": [],
    }


def test_intent_clarification_and_example_requests():
    clarification = classify_candidate_intent("не понял, что именно?", _ctx())
    assert clarification["intent"] == "clarification_request"
    assert clarification["should_count_as_answer"] is False
    assert clarification["recommended_policy"] == "clarify"

    example = classify_candidate_intent("какой кейс?", _ctx())
    assert example["intent"] == "request_example"
    assert example["should_count_as_answer"] is False
    assert example["recommended_policy"] == "give_example_scenario"


def test_intent_challenge_and_resume_focus():
    challenge = classify_candidate_intent("а ты сам знаешь ответ?", _ctx())
    assert challenge["intent"] == "challenge_interviewer"
    assert challenge["should_count_as_answer"] is False
    assert challenge["recommended_policy"] == "answer_meta_then_redirect"

    resume_focus = classify_candidate_intent("давай по моему опыту", _ctx())
    assert resume_focus["intent"] == "request_resume_focus"
    assert resume_focus["should_count_as_answer"] is False
    assert resume_focus["recommended_policy"] == "resume_redirect"


def test_intent_meta_and_weak_answer():
    meta = classify_candidate_intent("по резюме еще будут вопросы?", _ctx())
    assert meta["intent"] in {"meta_question", "request_resume_focus"}
    assert meta["should_count_as_answer"] is False

    weak = classify_candidate_intent("логи", _ctx())
    assert weak["intent"] == "weak_answer"
    assert weak["should_count_as_answer"] is True
    assert weak["should_advance_scenario"] is False

