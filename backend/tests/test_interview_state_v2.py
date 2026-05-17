import pytest

from app.services import interview_service
from app.services.interview_service import (
    _INTERVIEW_STATE_V2_KEY,
    _is_interview_engine_v2_enabled,
    _resume_deep_dive_force_transition,
    _resume_deep_dive_gate_opened,
    _update_resume_evidence,
    get_interview_state_v2,
    update_interview_state_v2,
)


class _InterviewStub:
    def __init__(self, *, role: str = "qa_engineer", language: str = "ru", state=None):
        self.target_role = role
        self.language = language
        self.interview_state = state


def test_interview_engine_version_normalizes_known_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "v2")
    assert interview_service.settings.interview_engine_version == "v2"
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "unknown")
    assert interview_service.settings.interview_engine_version == "v1"


def test_get_interview_state_v2_returns_default_shape_when_absent():
    interview = _InterviewStub()

    state = get_interview_state_v2(interview)

    assert state["engine_version"] == "v2"
    assert state["phase"] == "intro"
    assert state["role"] == "qa_engineer"
    assert state["language"] == "ru"
    assert state["current_competency"] is None
    assert state["current_scenario_id"] is None
    assert state["scenario_step"] == 0
    assert state["attempts_on_current_step"] == 0
    assert state["confusion_count"] == 0
    assert state["repeated_question_count"] == 0
    assert state["semantic_repeated_question_count"] == 0
    assert state["covered_competencies"] == []
    assert state["validated_competencies"] == []
    assert state["weak_competencies"] == []
    assert state["asked_questions"] == []
    assert state["conversational_intent_history"] == []
    assert state["information_target_history"] == []
    assert state["last_answer_evaluation"] is None
    assert state["next_action"] is None
    assert state["resume_scored_turns"] == 0


def test_get_interview_state_v2_merges_defaults_for_partial_payload():
    interview = _InterviewStub(
        role="backend_engineer",
        language="en",
        state={
            _INTERVIEW_STATE_V2_KEY: {
                "engine_version": "v2",
                "phase": "technical_case",
                "current_competency": "System Design & Architecture",
            }
        },
    )

    state = get_interview_state_v2(interview)

    assert state["engine_version"] == "v2"
    assert state["phase"] == "technical_case"
    assert state["role"] == "backend_engineer"
    assert state["language"] == "en"
    assert state["current_competency"] == "System Design & Architecture"
    assert state["asked_questions"] == []
    assert state["conversational_intent_history"] == []
    assert state["information_target_history"] == []
    assert state["last_answer_evaluation"] is None


def test_update_interview_state_v2_persists_under_nested_key_without_dropping_v1_state():
    interview = _InterviewStub(
        state={
            "turn_count": 4,
            "topic_signals": ["partial"],
        }
    )

    updated = update_interview_state_v2(
        interview,
        {
            "phase": "technical_deep_dive",
            "next_action": "follow_up",
            "asked_questions": ["Q1", "Q2"],
        },
    )

    assert updated["phase"] == "technical_deep_dive"
    assert updated["next_action"] == "follow_up"
    assert updated["asked_questions"] == ["Q1", "Q2"]

    assert interview.interview_state["turn_count"] == 4
    assert interview.interview_state["topic_signals"] == ["partial"]
    assert _INTERVIEW_STATE_V2_KEY in interview.interview_state
    assert interview.interview_state[_INTERVIEW_STATE_V2_KEY]["phase"] == "technical_deep_dive"


def test_v2_flag_can_be_enabled_without_breaking_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "v2")
    assert interview_service.settings.interview_engine_version == "v2"


def test_v2_role_gating_enables_only_whitelisted_roles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "v2")
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_V2_ROLES", "qa_engineer")
    assert _is_interview_engine_v2_enabled(role="qa_engineer") is True
    assert _is_interview_engine_v2_enabled(role="backend_engineer") is False


def test_v2_role_gating_with_empty_list_keeps_global_v2(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "v2")
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_V2_ROLES", "")
    assert _is_interview_engine_v2_enabled(role="qa_engineer") is True
    assert _is_interview_engine_v2_enabled(role="backend_engineer") is True


def test_v2_role_gating_disabled_when_version_is_v1(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_VERSION", "v1")
    monkeypatch.setattr(interview_service.settings, "INTERVIEW_ENGINE_V2_ROLES", "qa_engineer")
    assert _is_interview_engine_v2_enabled(role="qa_engineer") is False


def test_resume_gate_requires_evidence_before_opening():
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
    assert evidence["resume_questions_count"] == 1

    evidence = _update_resume_evidence(
        resume_evidence=evidence,
        answer=(
            "Например, в инциденте по платежам мы собрали request id и проверили логи, "
            "после фикса дефект не повторился."
        ),
        answer_evaluation={"has_personal_action": False, "has_result": True},
        topic_phase="resume_followup",
    )
    assert evidence["resume_questions_count"] >= 2
    assert _resume_deep_dive_gate_opened(evidence) is False

    evidence = _update_resume_evidence(
        resume_evidence=evidence,
        answer="Я лично воспроизвел дефект, проверил request id и подтвердил результат на ретесте.",
        answer_evaluation={"has_personal_action": True, "has_result": True},
        topic_phase="resume_followup",
    )
    assert _resume_deep_dive_gate_opened(evidence) is True


def test_resume_force_transition_after_max_scored_turns():
    assert _resume_deep_dive_force_transition(resume_scored_turns=0) is False
    assert _resume_deep_dive_force_transition(resume_scored_turns=3) is False
    assert _resume_deep_dive_force_transition(resume_scored_turns=4) is True
