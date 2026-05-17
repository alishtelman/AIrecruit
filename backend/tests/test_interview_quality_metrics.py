from app.services.interview_service import (
    _build_live_smoke_summary,
    _default_interview_quality_metrics,
    _normalize_interview_quality_metrics,
    _update_interview_quality_metrics,
)


def test_update_interview_quality_metrics_counts_expected_signals():
    metrics = _default_interview_quality_metrics()
    trace = {
        "selected_generator": "strategist",
        "strategist_json_valid": True,
        "was_question_rejected_as_repeated": False,
        "current_phase_after": "technical_case",
        "policy_action": "pressure_followup",
    }

    updated = _update_interview_quality_metrics(
        metrics=metrics,
        trace=trace,
        should_count_as_answer=True,
        phase_after="technical_case",
        policy_action="pressure_followup",
    )

    assert updated["total_turns"] == 1
    assert updated["scored_questions"] == 1
    assert updated["strategist_success_count"] == 1
    assert updated["fallback_count"] == 0
    assert updated["repeated_question_count"] == 0
    assert updated["semantic_repeated_question_count"] == 0
    assert updated["technical_case_turns"] == 1
    assert updated["pressure_followup_count"] == 1
    assert updated["clarification_count"] == 0


def test_update_interview_quality_metrics_counts_fallback_and_clarification():
    metrics = _default_interview_quality_metrics()
    trace = {
        "selected_generator": "strategist",
        "strategist_json_valid": False,
        "was_question_rejected_as_repeated": True,
        "current_phase_after": "resume_deep_dive",
        "policy_action": "clarify",
    }

    updated = _update_interview_quality_metrics(
        metrics=metrics,
        trace=trace,
        should_count_as_answer=False,
        phase_after="resume_deep_dive",
        policy_action="clarify",
    )

    assert updated["total_turns"] == 1
    assert updated["scored_questions"] == 0
    assert updated["strategist_success_count"] == 0
    assert updated["fallback_count"] == 1
    assert updated["repeated_question_count"] == 1
    assert updated["semantic_repeated_question_count"] == 0
    assert updated["resume_phase_turns"] == 1
    assert updated["technical_case_turns"] == 0
    assert updated["pressure_followup_count"] == 0
    assert updated["clarification_count"] == 1


def test_live_smoke_summary_contains_all_metrics():
    metrics = _normalize_interview_quality_metrics(
        {
            "total_turns": 11,
            "scored_questions": 9,
            "strategist_success_count": 8,
            "fallback_count": 1,
            "repeated_question_count": 0,
            "semantic_repeated_question_count": 0,
            "resume_phase_turns": 3,
            "technical_case_turns": 7,
            "pressure_followup_count": 2,
            "clarification_count": 1,
        }
    )
    summary = _build_live_smoke_summary(metrics)
    assert "turns=11" in summary
    assert "scored=9" in summary
    assert "strategist_success=8" in summary
    assert "fallbacks=1" in summary
    assert "repeats=0" in summary
    assert "semantic_repeats=0" in summary


def test_update_interview_quality_metrics_counts_semantic_repeat():
    metrics = _default_interview_quality_metrics()
    trace = {
        "selected_generator": "semantic_anti_loop",
        "strategist_json_valid": True,
        "was_question_rejected_as_repeated": True,
        "semantic_repeat_detected": True,
        "current_phase_after": "resume_deep_dive",
        "policy_action": "clarify",
    }

    updated = _update_interview_quality_metrics(
        metrics=metrics,
        trace=trace,
        should_count_as_answer=False,
        phase_after="resume_deep_dive",
        policy_action="clarify",
    )

    assert updated["repeated_question_count"] == 1
    assert updated["semantic_repeated_question_count"] == 1
