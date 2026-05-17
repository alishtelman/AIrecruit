from app.ai.interview_policy import decide_interview_policy


def test_policy_non_answer_does_not_advance():
    policy = decide_interview_policy(
        state={"weak_answer_streak": 0, "last_step_key": "a", "current_step_key": "a"},
        intent_result={
            "intent": "challenge_interviewer",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "answer_meta_then_redirect",
        },
        answer_evaluation={"quality": "no_signal"},
    )
    assert policy["policy_action"] == "answer_meta_then_redirect"
    assert policy["count_as_scored_answer"] is False
    assert policy["advance_phase"] is False
    assert policy["advance_scenario"] is False


def test_policy_weak_answer_forces_pressure_then_allows_progress():
    first = decide_interview_policy(
        state={"weak_answer_streak": 0, "last_step_key": "a", "current_step_key": "a"},
        intent_result={
            "intent": "weak_answer",
            "should_count_as_answer": True,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "pressure_followup",
        },
        answer_evaluation={"quality": "weak"},
    )
    assert first["policy_action"] == "pressure_followup"
    assert first["advance_scenario"] is False

    second = decide_interview_policy(
        state={"weak_answer_streak": 1, "last_step_key": "a", "current_step_key": "a"},
        intent_result={
            "intent": "weak_answer",
            "should_count_as_answer": True,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "pressure_followup",
        },
        answer_evaluation={"quality": "weak"},
    )
    assert second["policy_action"] == "switch_topic"
    assert second["advance_scenario"] is True
    assert second["update_weak_answer_count"] is True

