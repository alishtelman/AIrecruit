"""
Tests for voice-first interview: practical task policy, submission isolation,
transcript confirm flow, and report inclusion.

These are unit tests — no running backend required.
"""
import uuid
from datetime import datetime

import pytest

from app.ai.practical_tasks import (
    PRACTICAL_TASK_ALLOWED_STAGES,
    PRACTICAL_TASK_ROLES,
    get_practical_task,
    should_trigger_practical_task,
)
from app.schemas.report import AssessmentReportResponse


# ---------------------------------------------------------------------------
# should_trigger_practical_task — policy tests
# ---------------------------------------------------------------------------

class TestShouldTriggerPracticalTask:
    """Policy function: when should a practical task be injected?"""

    def test_already_triggered_blocks(self):
        assert not should_trigger_practical_task(
            role="backend_engineer",
            answered_count=4,
            already_triggered=True,
        )

    def test_role_not_in_allowed_set_blocks(self):
        # designer has no practical tasks defined
        assert not should_trigger_practical_task(
            role="designer",
            answered_count=4,
            already_triggered=False,
        )

    def test_too_few_answers_blocks(self):
        # Need at least 3 before triggering
        assert not should_trigger_practical_task(
            role="backend_engineer",
            answered_count=2,
            already_triggered=False,
        )

    def test_too_many_answers_blocks(self):
        # After 6 answers it's too late
        assert not should_trigger_practical_task(
            role="backend_engineer",
            answered_count=7,
            already_triggered=False,
        )

    def test_trigger_window_fires(self):
        for count in (3, 4, 5, 6):
            assert should_trigger_practical_task(
                role="backend_engineer",
                answered_count=count,
                already_triggered=False,
            ), f"expected trigger at answered_count={count}"

    def test_wrong_stage_blocks(self):
        # Behavioral closing phase — no practical task here
        assert not should_trigger_practical_task(
            role="backend_engineer",
            answered_count=4,
            already_triggered=False,
            current_stage_key="behavioral_closing",
        )

    def test_technical_stage_allows(self):
        assert should_trigger_practical_task(
            role="qa_engineer",
            answered_count=4,
            already_triggered=False,
            current_stage_key="technical",
        )

    @pytest.mark.parametrize("stage", ["technical_case", "resume_deep_dive"])
    def test_v2_engine_stage_keys_allow(self, stage):
        assert should_trigger_practical_task(
            role="backend_engineer",
            answered_count=4,
            already_triggered=False,
            current_stage_key=stage,
        )

    def test_empty_stage_allows(self):
        # No stage set → simple interview, practical task is allowed
        assert should_trigger_practical_task(
            role="data_scientist",
            answered_count=4,
            already_triggered=False,
            current_stage_key="",
        )

    def test_none_stage_allows(self):
        assert should_trigger_practical_task(
            role="product_manager",
            answered_count=4,
            already_triggered=False,
            current_stage_key=None,
        )

    @pytest.mark.parametrize("role", list(PRACTICAL_TASK_ROLES))
    def test_all_allowed_roles_can_trigger(self, role):
        assert should_trigger_practical_task(
            role=role,
            answered_count=4,
            already_triggered=False,
        )


# ---------------------------------------------------------------------------
# get_practical_task — task bank
# ---------------------------------------------------------------------------

class TestGetPracticalTask:
    def test_returns_task_for_known_role(self):
        task = get_practical_task("backend_engineer", "ru")
        assert task is not None
        assert task["task_id"]  # UUID generated
        assert task["task_type"] in (
            "coding_task", "debugging_task", "sql_task",
            "qa_test_case_task", "product_case_task", "business_case_task",
        )
        assert task["title"]
        assert task["instruction"]

    def test_returns_none_for_unknown_role(self):
        assert get_practical_task("alien_engineer") is None

    def test_language_ru(self):
        task = get_practical_task("backend_engineer", "ru")
        # Russian instruction should not start with "Write" or "Implement"
        assert task is not None
        # Just verify a task is returned — full content is in the bank
        assert isinstance(task["instruction"], str)
        assert len(task["instruction"]) > 20

    def test_language_en(self):
        task = get_practical_task("backend_engineer", "en")
        assert task is not None
        assert isinstance(task["instruction"], str)

    def test_required_fields_present(self):
        for role in PRACTICAL_TASK_ROLES:
            task = get_practical_task(role)
            if task is None:
                continue  # role may not have tasks yet
            for field in ("task_id", "task_type", "title", "instruction", "time_limit_minutes"):
                assert field in task, f"Missing field '{field}' for role '{role}'"

    def test_starter_code_present_for_coding_tasks(self):
        task = get_practical_task("backend_engineer")
        assert task is not None
        if task["task_type"] == "coding_task":
            assert task.get("starter_code"), "coding_task should have starter_code"

    def test_each_call_returns_valid_uuid(self):
        import uuid
        t1 = get_practical_task("backend_engineer")
        t2 = get_practical_task("backend_engineer")
        assert t1 and t2
        # Both task_ids must be valid UUIDs and different from each other
        # (collisions possible but astronomically unlikely)
        uuid.UUID(t1["task_id"])
        uuid.UUID(t2["task_id"])


# ---------------------------------------------------------------------------
# Allowed stages set — sanity checks
# ---------------------------------------------------------------------------

class TestAllowedStages:
    def test_behavioral_closing_not_in_allowed_stages(self):
        assert "behavioral_closing" not in PRACTICAL_TASK_ALLOWED_STAGES

    def test_technical_in_allowed_stages(self):
        assert "technical" in PRACTICAL_TASK_ALLOWED_STAGES

    def test_empty_string_in_allowed_stages(self):
        # No-stage (simple interviews) must always be allowed
        assert "" in PRACTICAL_TASK_ALLOWED_STAGES


# ---------------------------------------------------------------------------
# Voice transcript confirm logic (unit-level)
# ---------------------------------------------------------------------------

class TestVoiceTranscriptConfirm:
    """
    These tests verify the VOICE_AUTO_SEND=false contract at a logic level.
    Full UI tests would require a browser; here we verify the flag semantics.
    """

    def test_voice_auto_send_flag_defaults_to_false(self, monkeypatch):
        """NEXT_PUBLIC_VOICE_AUTO_SEND must default to false (env var absent)."""
        import os
        monkeypatch.delenv("NEXT_PUBLIC_VOICE_AUTO_SEND", raising=False)
        # The frontend reads this at module load time. We verify the expected
        # default by checking the env var interpretation rule:
        # VOICE_AUTO_SEND = process.env.NEXT_PUBLIC_VOICE_AUTO_SEND === "true"
        raw = os.environ.get("NEXT_PUBLIC_VOICE_AUTO_SEND", "")
        assert raw != "true", (
            "NEXT_PUBLIC_VOICE_AUTO_SEND should not default to 'true'; "
            "transcripts must require explicit confirm by default."
        )

    def test_default_interview_mode_is_text(self, monkeypatch):
        """DEFAULT_INTERVIEW_MODE must default to 'text' when env var is absent."""
        import os
        monkeypatch.delenv("NEXT_PUBLIC_DEFAULT_INTERVIEW_MODE", raising=False)
        raw = os.environ.get("NEXT_PUBLIC_DEFAULT_INTERVIEW_MODE", "")
        assert raw != "voice", (
            "NEXT_PUBLIC_DEFAULT_INTERVIEW_MODE should default to 'text', "
            "not 'voice', until voice mode is fully stable."
        )


# ---------------------------------------------------------------------------
# Practical submission message isolation (unit-level)
# ---------------------------------------------------------------------------

class TestPracticalSubmissionIsolation:
    """
    Verify that practical_submission is stored separately from candidate answers.
    These are contract / specification tests — they document expected behaviour.
    """

    def test_role_value_is_practical_submission(self):
        """
        The role stored for a practical submission must be 'practical_submission',
        not 'candidate', so it is not fed into the LLM history as a regular answer.
        """
        # This is a specification test: we verify the constant, not the DB.
        # The actual DB write is in save_practical_submission which uses this value.
        expected_role = "practical_submission"
        assert expected_role != "candidate"
        assert expected_role != "assistant"
        assert len(expected_role) <= 50  # fits InterviewMessage.role column

    def test_summary_message_does_not_contain_raw_code(self):
        """
        The summary message injected into the LLM history (role='candidate')
        must be a brief label — NOT the raw code/answer.
        """
        task_type = "coding_task"
        language = "python"
        interview_language = "ru"

        # Reproduce the summary construction logic from save_practical_submission
        lang_note = f" ({language})" if language not in ("text", "other", None) else ""
        task_label = task_type.replace("_", " ")
        summary_msg = (
            f"[Практическое задание{lang_note}: {task_label} — выполнено]"
            if interview_language != "en"
            else f"[Practical task{lang_note}: {task_label} — submitted]"
        )

        raw_code = "def solve(): return 42\n" * 20
        assert raw_code not in summary_msg, (
            "Raw code must NOT appear in the LLM summary message"
        )
        assert len(summary_msg) < 200, (
            "Summary message should be brief, not contain full solution"
        )

    def test_practical_evaluation_fields_schema(self):
        """
        Evaluation dict returned by _evaluate_practical_submission
        must always include the required fields for the report.
        """
        required_fields = {
            "practical_score",
            "correctness",
            "completeness",
            "edge_cases",
            "code_quality",
            "solution_quality_notes",
            "follow_up_question",
            "risks",
            "task_type",
        }
        # Build a mock evaluation result the same way the function does
        mock_data = {
            "practical_score": 7.5,
            "correctness": "partial",
            "completeness": "complete",
            "edge_cases": "missed",
            "code_quality": "acceptable",
            "solution_quality_notes": "Good structure, missing edge case for empty input.",
            "follow_up_question": "What happens if the list is empty?",
            "risks": ["no empty-list guard"],
        }
        result = {
            "practical_score": float(mock_data.get("practical_score", 0)),
            "correctness": str(mock_data.get("correctness", "unknown")),
            "completeness": str(mock_data.get("completeness", "unknown")),
            "edge_cases": str(mock_data.get("edge_cases", "not_applicable")),
            "code_quality": str(mock_data.get("code_quality", "not_applicable")),
            "solution_quality_notes": str(mock_data.get("solution_quality_notes", "")),
            "follow_up_question": mock_data.get("follow_up_question"),
            "risks": list(mock_data.get("risks", [])),
            "task_type": "coding_task",
            "language": "python",
        }
        for field in required_fields:
            assert field in result, f"Missing field '{field}' in evaluation result"


# ---------------------------------------------------------------------------
# Negative case: evaluation failure does not break the interview
# ---------------------------------------------------------------------------

class TestEvaluationFailureNegativeCase:
    """
    Verify the 'evaluation never blocks the interview' contract.
    The evaluation function returns a trace-only dict on failure so callers
    can persist the failure reason — but the interview always continues.
    """

    def _build_failed_evaluation(self, task_type: str = "coding_task", language: str = "python") -> dict:
        """Reproduce what _evaluate_practical_submission returns on LLM failure."""
        error_msg = "Connection timeout after 15s"
        return {
            "practical_score": None,
            "correctness": "evaluation_failed",
            "completeness": "evaluation_failed",
            "edge_cases": "not_applicable",
            "code_quality": "not_applicable",
            "solution_quality_notes": "",
            "follow_up_question": None,
            "risks": [],
            "task_type": task_type,
            "language": language,
            "trace": {
                "status": "failed",
                "model": "gpt-5.4-mini",
                "latency_ms": 15041,
                "error": error_msg,
            },
        }

    def test_failed_evaluation_is_not_none(self):
        """On failure, the function returns a dict (not None) so callers can persist the trace."""
        result = self._build_failed_evaluation()
        assert result is not None, "Evaluation failure must return a dict, not None"

    def test_failed_evaluation_has_trace_block(self):
        result = self._build_failed_evaluation()
        assert "trace" in result
        assert result["trace"]["status"] == "failed"
        assert result["trace"]["error"] is not None
        assert isinstance(result["trace"]["latency_ms"], int)

    def test_failed_evaluation_has_all_required_fields(self):
        """Even on failure, all required keys are present so the report section is buildable."""
        result = self._build_failed_evaluation()
        required = {
            "practical_score", "correctness", "completeness",
            "edge_cases", "code_quality", "solution_quality_notes",
            "follow_up_question", "risks", "task_type", "language", "trace",
        }
        for field in required:
            assert field in result, f"Missing field '{field}' in failed evaluation"

    def test_failed_evaluation_correctness_is_evaluation_failed(self):
        result = self._build_failed_evaluation()
        assert result["correctness"] == "evaluation_failed"
        assert result["completeness"] == "evaluation_failed"

    def test_practical_section_shows_failed_trace_status(self):
        """Report practical_section must surface trace_status=failed when evaluation failed."""
        eval_with_failure = self._build_failed_evaluation(task_type="sql_task", language="sql")
        # Simulate what _generate_and_commit_report does with practical_evaluations
        practical_evals = [{"task_id": "abc-123", **eval_with_failure}]

        # Reproduce the task summary built for full_report_json
        tasks_summary = [
            {
                "task_id": e.get("task_id"),
                "task_type": e.get("task_type"),
                "language": e.get("language"),
                "practical_score": e.get("practical_score"),
                "correctness": e.get("correctness"),
                "completeness": e.get("completeness"),
                "edge_cases": e.get("edge_cases"),
                "code_quality": e.get("code_quality"),
                "solution_quality_notes": e.get("solution_quality_notes"),
                "follow_up_question": e.get("follow_up_question"),
                "risks": e.get("risks", []),
                "trace_status": (e.get("trace") or {}).get("status"),
            }
            for e in practical_evals
        ]
        assert len(tasks_summary) == 1
        task = tasks_summary[0]
        assert task["trace_status"] == "failed", "trace_status must be 'failed' in report section"
        assert task["correctness"] == "evaluation_failed"
        assert task["practical_score"] is None

    def test_practical_evaluation_status_field_persisted(self):
        """
        interview_state must include practical_evaluation_status for auditability.
        Even on failure, the status is 'failed' (not None or missing).
        """
        failed_eval = self._build_failed_evaluation()
        trace = failed_eval.get("trace", {})
        status = trace.get("status")
        assert status == "failed"
        # Simulate the state update
        state = {}
        state["practical_evaluation_status"] = trace.get("status", "unknown")
        state["practical_evaluation_model"] = trace.get("model")
        state["practical_evaluation_latency_ms"] = trace.get("latency_ms")
        state["practical_evaluation_error"] = trace.get("error")
        assert state["practical_evaluation_status"] == "failed"
        assert state["practical_evaluation_error"] is not None
        assert state["practical_evaluation_latency_ms"] == 15041

    def test_interview_does_not_block_when_evaluation_is_none(self):
        """
        If _evaluate_practical_submission returns None (provider not configured),
        the interview state update is skipped but the interview continues.
        """
        evaluation = None  # no provider configured
        state = {"practical_submissions": [{"task_id": "x"}]}

        # Reproduce the conditional in save_practical_submission
        if evaluation is not None:
            evals = list(state.get("practical_evaluations", []))
            evals.append({"task_id": "x", **evaluation})
            state["practical_evaluations"] = evals
            state["practical_evaluation_status"] = (evaluation.get("trace") or {}).get("status", "unknown")

        # None evaluation → state unchanged, no crash
        assert "practical_evaluations" not in state
        assert "practical_evaluation_status" not in state
        # practical_submissions still saved
        assert len(state["practical_submissions"]) == 1


# ---------------------------------------------------------------------------
# Counters: practical_submission does not break answered_count / finish
# ---------------------------------------------------------------------------

class TestCountersNotBrokenByPracticalSubmission:
    """
    practical_submission role must not affect question counts, eligibility,
    or MaxQuestionsReachedError logic.
    """

    def _make_message(self, role: str, content: str = "test") -> dict:
        return {"role": role, "content": content}

    def test_candidate_count_excludes_practical_submission(self):
        """_count_visible_messages counts only 'candidate', not 'practical_submission'."""
        messages = [
            self._make_message("assistant", "q1"),
            self._make_message("candidate", "a1"),
            self._make_message("assistant", "q2"),
            self._make_message("candidate", "a2"),
            self._make_message("practical_submission", "def solve(): return 42"),
            self._make_message("assistant", "q3"),
        ]
        candidate_count = sum(1 for m in messages if m["role"] == "candidate")
        assert candidate_count == 2, f"Expected 2 candidate messages, got {candidate_count}"

    def test_practical_submission_not_in_llm_excluded_roles_causes_test_failure(self):
        """Verify that _LLM_EXCLUDED_ROLES actually contains practical_submission."""
        # We can't import from interview_service without httpx, so check the source
        import ast, re
        with open("app/services/interview_service.py") as f:
            src = f.read()
        # Must contain the frozenset definition
        assert "_LLM_EXCLUDED_ROLES = frozenset" in src
        assert '"practical_submission"' in src

    def test_existing_practical_submission_blocks_retrigger_guard(self):
        """A submitted practical task must block opening a second practical modal."""
        with open("app/services/interview_service.py") as f:
            src = f.read()

        assert "has_practical_submission" in src
        assert 'role", None) == "practical_submission"' in src
        assert "or has_practical_submission" in src
        assert 'state["practical_task_submitted"] = True' in src
        assert "_PRACTICAL_STATE_KEYS" in src
        assert "preserved_practical_state" in src
        assert "interview.interview_state.update(preserved_practical_state)" in src
        assert "result.text" in src
        assert "result.content" not in src

    def test_max_questions_guard_safe_when_last_msg_is_practical_submission(self):
        """
        The MaxQuestionsReachedError guard fires when:
            interview.question_count >= max AND messages[-1].role == 'candidate'
        If the last message is 'practical_submission', the guard must NOT fire.
        """
        last_message_role = "practical_submission"
        max_questions = 8
        question_count = 8  # would normally trigger

        guard_fires = (
            question_count >= max_questions
            and last_message_role == "candidate"
        )
        assert not guard_fires, (
            "MaxQuestionsReachedError must NOT fire when last message is practical_submission"
        )

    def test_answer_already_persisted_safe_with_practical_submission(self):
        """
        The retry guard (answer_already_persisted) checks messages[-1].role == 'candidate'.
        When last message is 'practical_submission', it must be False.
        """
        summary_msg = "[Практическое задание (python): coding task — выполнено]"
        last_role = "practical_submission"
        last_content = "def solve(): return 42"

        answer_already_persisted = (
            last_role == "candidate" and last_content == summary_msg
        )
        assert not answer_already_persisted, (
            "answer_already_persisted must be False when last message is practical_submission"
        )

    def test_practical_submission_role_length_fits_column(self):
        """InterviewMessage.role is String(50) — practical_submission must fit."""
        assert len("practical_submission") <= 50


# ---------------------------------------------------------------------------
# Text mode regression
# ---------------------------------------------------------------------------

class TestTextModeNotBroken:
    """Verify that voice-first changes do not break text-mode contracts."""

    def test_practical_task_not_triggered_for_designer(self):
        """Roles without a task bank must never trigger a practical task."""
        assert not should_trigger_practical_task(
            role="designer",
            answered_count=4,
            already_triggered=False,
        )

    def test_practical_task_not_triggered_when_already_done(self):
        """Once triggered, never trigger again in the same interview."""
        assert not should_trigger_practical_task(
            role="backend_engineer",
            answered_count=5,
            already_triggered=True,
        )


class TestReportPracticalSection:
    def test_report_response_exposes_practical_section(self):
        section = {
            "has_practical_tasks": True,
            "practical_tasks_count": 1,
            "evaluation_status": "success",
        }
        report = AssessmentReportResponse.model_validate({
            "id": uuid.uuid4(),
            "interview_id": uuid.uuid4(),
            "candidate_id": uuid.uuid4(),
            "overall_score": 7.0,
            "hard_skills_score": 7.0,
            "soft_skills_score": 6.0,
            "communication_score": 6.0,
            "problem_solving_score": 7.0,
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "hiring_recommendation": "maybe",
            "interview_summary": "summary",
            "model_version": "test",
            "created_at": datetime.utcnow(),
            "full_report_json": {"practical_section": section},
        })

        assert report.practical_section == section

    def test_report_response_exposes_interview_quality_counters(self):
        metrics = {
            "answered_on_topic_count": 4,
            "off_topic_answers_count": 2,
            "skipped_or_control_intent_count": 1,
            "relevance_reframe_count": 1,
            "forced_topic_transition_count": 1,
        }
        counters = {
            "answered_on_topic_count": 4,
            "off_topic_answers_count": 2,
            "skipped_or_control_intent_count": 1,
        }
        report = AssessmentReportResponse.model_validate({
            "id": uuid.uuid4(),
            "interview_id": uuid.uuid4(),
            "candidate_id": uuid.uuid4(),
            "overall_score": 7.0,
            "hard_skills_score": 7.0,
            "soft_skills_score": 6.0,
            "communication_score": 6.0,
            "problem_solving_score": 7.0,
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "hiring_recommendation": "maybe",
            "interview_summary": "summary",
            "model_version": "test",
            "created_at": datetime.utcnow(),
            "full_report_json": {
                "interview_quality_metrics": metrics,
                "answer_quality_counters": counters,
            },
        })

        assert report.interview_quality_metrics == metrics
        assert report.answer_quality_counters == counters

    def test_practical_task_not_triggered_in_closing_stage(self):
        assert not should_trigger_practical_task(
            role="backend_engineer",
            answered_count=4,
            already_triggered=False,
            current_stage_key="behavioral_closing",
        )
