from __future__ import annotations

from typing import Any


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def decide_interview_policy(
    state: dict[str, Any] | None,
    intent_result: dict[str, Any],
    answer_evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    state = state or {}
    eval_data = answer_evaluation or {}
    intent = str(intent_result.get("intent") or "answer")
    recommended_policy = str(intent_result.get("recommended_policy") or "continue")
    quality = str(eval_data.get("quality") or "no_signal")

    weak_streak = _safe_int(state.get("weak_answer_streak"), 0)
    last_step_key = str(state.get("last_step_key") or "")
    current_step_key = str(state.get("current_step_key") or "")
    same_step = bool(current_step_key and current_step_key == last_step_key)

    policy_action = "continue"
    count_as_scored_answer = True
    advance_phase = True
    advance_scenario = True
    update_confusion_count = False
    update_weak_answer_count = False
    reason = "default_continue"

    if intent != "answer":
        count_as_scored_answer = bool(intent_result.get("should_count_as_answer", False))
        advance_phase = bool(intent_result.get("should_advance_phase", False))
        advance_scenario = bool(intent_result.get("should_advance_scenario", False))
        policy_action = recommended_policy
        reason = f"intent_driven_{intent}"
        if intent in {"clarification_request", "request_example"}:
            update_confusion_count = True
        if intent in {"dont_know", "weak_answer"}:
            update_weak_answer_count = True

    if intent == "weak_answer" or quality == "weak":
        update_weak_answer_count = True
        count_as_scored_answer = True
        if same_step and weak_streak >= 1:
            # Avoid loops: after one pressure attempt on same step we can move on.
            policy_action = "switch_topic"
            advance_phase = True
            advance_scenario = True
            reason = "repeated_weak_answer_allow_progress_with_weak_mark"
        else:
            policy_action = "pressure_followup"
            advance_phase = False
            advance_scenario = False
            reason = "weak_answer_requires_pressure_followup"

    if intent in {"clarification_request", "request_example"}:
        policy_action = "clarify" if intent == "clarification_request" else "give_example_scenario"
        count_as_scored_answer = False
        advance_phase = False
        advance_scenario = False
        update_confusion_count = True
        reason = f"{intent}_do_not_advance"

    if intent in {"meta_question", "challenge_interviewer"}:
        policy_action = "answer_meta_then_redirect"
        count_as_scored_answer = False
        advance_phase = False
        advance_scenario = False
        update_confusion_count = True
        reason = f"{intent}_answer_then_redirect"

    if intent == "request_resume_focus":
        policy_action = "resume_redirect"
        count_as_scored_answer = False
        advance_phase = False
        advance_scenario = False
        reason = "candidate_requested_resume_focus"

    if intent == "offtopic":
        policy_action = "switch_topic"
        count_as_scored_answer = False
        advance_phase = False
        advance_scenario = False
        reason = "offtopic_message"

    if intent == "end_interview":
        policy_action = "close_interview"
        count_as_scored_answer = False
        advance_phase = True
        advance_scenario = True
        reason = "candidate_requested_manual_finish"

    if intent == "answer" and quality in {"strong", "medium"}:
        policy_action = "continue"
        count_as_scored_answer = True
        advance_phase = True
        advance_scenario = True
        reason = f"{quality}_answer_continue"

    return {
        "policy_action": policy_action,
        "count_as_scored_answer": count_as_scored_answer,
        "advance_phase": advance_phase,
        "advance_scenario": advance_scenario,
        "update_confusion_count": update_confusion_count,
        "update_weak_answer_count": update_weak_answer_count,
        "reason": reason,
    }
