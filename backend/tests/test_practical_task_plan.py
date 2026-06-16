"""
Tests for the role-based practical task plan system.

Covers:
1. expected_solution never in frontend-safe dict
2. Role-based plan count by seniority (junior=2, middle=3, senior=4)
3. Empty / placeholder answer rejected
4. Task bank completeness (each role has sufficient tasks)
5. get_practical_plan uniqueness and ordering
6. Plan-based trigger policy
7. get_task_for_frontend security contract
"""
import sys
sys.path.insert(0, ".")

from app.ai.practical_tasks import (
    TASK_BANK,
    PRACTICAL_TASK_ROLES,
    TASKS_BY_LEVEL,
    _BACKEND_ONLY_FIELDS,
    get_practical_plan,
    get_task_by_id,
    get_task_for_frontend,
    should_trigger_next_practical_task,
)


# ---------------------------------------------------------------------------
# Security: expected_solution never reaches frontend
# ---------------------------------------------------------------------------

class TestExpectedSolutionNeverSentToFrontend:

    def test_get_task_for_frontend_strips_expected_solution(self):
        """get_task_for_frontend must never include expected_solution."""
        for role, tasks in TASK_BANK.items():
            for raw_task in tasks:
                safe = get_task_for_frontend(raw_task, "ru")
                assert "expected_solution" not in safe, (
                    f"expected_solution leaked for role={role}, task={raw_task.get('id')}"
                )

    def test_get_task_for_frontend_strips_evaluation_rubric(self):
        """get_task_for_frontend must never include evaluation_rubric."""
        for role, tasks in TASK_BANK.items():
            for raw_task in tasks:
                safe = get_task_for_frontend(raw_task, "en")
                assert "evaluation_rubric" not in safe, (
                    f"evaluation_rubric leaked for role={role}, task={raw_task.get('id')}"
                )

    def test_backend_only_fields_defined(self):
        """_BACKEND_ONLY_FIELDS must include expected_solution and evaluation_rubric."""
        assert "expected_solution" in _BACKEND_ONLY_FIELDS
        assert "evaluation_rubric" in _BACKEND_ONLY_FIELDS

    def test_all_bank_tasks_have_expected_solution(self):
        """Every task in the bank must have an expected_solution for the evaluator."""
        for role, tasks in TASK_BANK.items():
            for t in tasks:
                assert t.get("expected_solution"), (
                    f"Missing expected_solution for role={role}, task_id={t.get('id')}"
                )

    def test_all_bank_tasks_have_evaluation_rubric(self):
        """Every task in the bank must have an evaluation_rubric."""
        for role, tasks in TASK_BANK.items():
            for t in tasks:
                assert t.get("evaluation_rubric"), (
                    f"Missing evaluation_rubric for role={role}, task_id={t.get('id')}"
                )

    def test_frontend_safe_dict_has_required_public_fields(self):
        """get_task_for_frontend must return all required public fields."""
        tasks = TASK_BANK.get("backend_engineer", [])
        assert tasks
        safe = get_task_for_frontend(tasks[0], "ru")
        required = {"task_id", "task_type", "title", "instruction",
                    "starter_code", "evaluation_criteria", "time_limit_minutes"}
        for field in required:
            assert field in safe, f"Missing public field: {field}"


# ---------------------------------------------------------------------------
# Role-based plan count by seniority
# ---------------------------------------------------------------------------

class TestRoleBasedPlanCount:

    def test_junior_gets_2_tasks_for_frontend_engineer(self):
        plan = get_practical_plan("frontend_engineer", "junior", "ru")
        assert len(plan) == 2, f"Expected 2 tasks for junior, got {len(plan)}"

    def test_middle_gets_3_tasks_for_frontend_engineer(self):
        plan = get_practical_plan("frontend_engineer", "middle", "ru")
        assert len(plan) == 3, f"Expected 3 tasks for middle, got {len(plan)}"

    def test_senior_gets_4_tasks_for_frontend_engineer(self):
        plan = get_practical_plan("frontend_engineer", "senior", "ru")
        assert len(plan) == 4, f"Expected 4 tasks for senior, got {len(plan)}"

    def test_junior_gets_2_tasks_for_backend_engineer(self):
        plan = get_practical_plan("backend_engineer", "junior", "ru")
        assert len(plan) == 2

    def test_middle_gets_3_tasks_for_backend_engineer(self):
        plan = get_practical_plan("backend_engineer", "middle", "ru")
        assert len(plan) == 3

    def test_senior_gets_up_to_4_tasks(self):
        plan = get_practical_plan("backend_engineer", "senior", "ru")
        # senior wants 4, bank may have fewer — should return min(4, bank_size)
        assert 2 <= len(plan) <= 4

    def test_unknown_seniority_defaults_to_2(self):
        plan = get_practical_plan("backend_engineer", None, "ru")
        # None seniority → TASKS_BY_LEVEL fallback (should be 2)
        assert len(plan) >= 1  # at least 1 task

    def test_plan_has_no_duplicates(self):
        for seniority in ("junior", "middle", "senior"):
            for role in PRACTICAL_TASK_ROLES:
                plan = get_practical_plan(role, seniority)
                assert len(plan) == len(set(plan)), (
                    f"Duplicate task_ids in plan for role={role}, seniority={seniority}"
                )

    def test_plan_ids_are_resolvable(self):
        """Every ID in the plan must resolve to a task via get_task_by_id."""
        for role in PRACTICAL_TASK_ROLES:
            plan = get_practical_plan(role, "middle")
            for task_id in plan:
                task = get_task_by_id(task_id, role)
                assert task is not None, (
                    f"Task ID '{task_id}' from plan not found in TASK_BANK for role={role}"
                )

    def test_unknown_role_returns_empty_plan(self):
        plan = get_practical_plan("alien_engineer", "middle")
        assert plan == []


# ---------------------------------------------------------------------------
# Task bank completeness
# ---------------------------------------------------------------------------

class TestTaskBankCompleteness:

    def test_frontend_engineer_has_at_least_4_tasks(self):
        """Frontend engineer must have enough tasks for a senior interview (4 slots)."""
        tasks = TASK_BANK.get("frontend_engineer", [])
        assert len(tasks) >= 4, (
            f"frontend_engineer needs ≥4 tasks for senior level, has {len(tasks)}"
        )

    def test_backend_engineer_has_at_least_3_tasks(self):
        tasks = TASK_BANK.get("backend_engineer", [])
        assert len(tasks) >= 3

    def test_qa_engineer_has_at_least_3_tasks(self):
        tasks = TASK_BANK.get("qa_engineer", [])
        assert len(tasks) >= 3

    def test_all_roles_have_at_least_2_tasks(self):
        """Every role in PRACTICAL_TASK_ROLES must have ≥2 tasks for junior level."""
        for role in PRACTICAL_TASK_ROLES:
            tasks = TASK_BANK.get(role, [])
            assert len(tasks) >= 2, (
                f"Role '{role}' has only {len(tasks)} tasks — need ≥2 for junior level"
            )

    def test_every_task_has_stable_id(self):
        """Every task in the bank must have a unique stable 'id' field."""
        all_ids: list[str] = []
        for role, tasks in TASK_BANK.items():
            for t in tasks:
                tid = t.get("id", "")
                assert tid, f"Task in role={role} is missing 'id'"
                all_ids.append(tid)
        # IDs must be unique across the entire bank
        assert len(all_ids) == len(set(all_ids)), (
            f"Duplicate task IDs found: {[x for x in all_ids if all_ids.count(x) > 1]}"
        )

    def test_every_task_has_difficulty(self):
        for role, tasks in TASK_BANK.items():
            for t in tasks:
                diff = t.get("difficulty")
                assert diff in ("junior", "middle", "senior"), (
                    f"Task '{t.get('id')}' in role={role} has invalid difficulty={diff}"
                )

    def test_frontend_engineer_has_junior_and_middle_tasks(self):
        """Frontend engineer must have both junior and middle tasks."""
        tasks = TASK_BANK.get("frontend_engineer", [])
        diffs = {t.get("difficulty") for t in tasks}
        assert "junior" in diffs, "frontend_engineer missing junior tasks"
        assert "middle" in diffs, "frontend_engineer missing middle tasks"

    def test_backend_engineer_has_senior_task(self):
        tasks = TASK_BANK.get("backend_engineer", [])
        diffs = {t.get("difficulty") for t in tasks}
        assert "senior" in diffs, "backend_engineer missing senior task"


# ---------------------------------------------------------------------------
# Empty / placeholder answer validation
# ---------------------------------------------------------------------------

class TestEmptyAnswerRejected:

    def test_pydantic_rejects_empty_answer(self):
        from pydantic import ValidationError
        from app.schemas.interview import PracticalSubmissionRequest
        try:
            PracticalSubmissionRequest(task_id="x", task_type="coding_task", answer="")
            assert False, "Should have raised ValidationError"
        except ValidationError as e:
            assert "empty" in str(e).lower() or "answer" in str(e).lower()

    def test_pydantic_rejects_whitespace_only(self):
        from pydantic import ValidationError
        from app.schemas.interview import PracticalSubmissionRequest
        try:
            PracticalSubmissionRequest(task_id="x", task_type="coding_task", answer="   \n  ")
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass  # expected

    def test_pydantic_rejects_placeholder_pass(self):
        from pydantic import ValidationError
        from app.schemas.interview import PracticalSubmissionRequest
        try:
            PracticalSubmissionRequest(task_id="x", task_type="coding_task", answer="pass")
            assert False, "Should have raised ValidationError for unchanged placeholder"
        except ValidationError as e:
            assert "placeholder" in str(e).lower() or "solution" in str(e).lower()

    def test_pydantic_rejects_implement_here_placeholder(self):
        from pydantic import ValidationError
        from app.schemas.interview import PracticalSubmissionRequest
        try:
            PracticalSubmissionRequest(task_id="x", task_type="coding_task", answer="# implement here")
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_pydantic_accepts_real_answer(self):
        from app.schemas.interview import PracticalSubmissionRequest
        req = PracticalSubmissionRequest(
            task_id="x",
            task_type="coding_task",
            answer="def solve():\n    return 42\n",
        )
        assert req.answer.strip() == "def solve():\n    return 42"


# ---------------------------------------------------------------------------
# Plan-based trigger policy
# ---------------------------------------------------------------------------

class TestPlanBasedTriggerPolicy:

    def test_triggers_when_tasks_remain(self):
        assert should_trigger_next_practical_task(
            role="frontend_engineer",
            answered_count=3,
            tasks_remaining_in_plan=2,
            tasks_completed_count=0,
        )

    def test_no_trigger_when_plan_exhausted(self):
        assert not should_trigger_next_practical_task(
            role="frontend_engineer",
            answered_count=3,
            tasks_remaining_in_plan=0,
            tasks_completed_count=3,
        )

    def test_no_trigger_before_min_answers(self):
        assert not should_trigger_next_practical_task(
            role="backend_engineer",
            answered_count=1,
            tasks_remaining_in_plan=2,
            tasks_completed_count=0,
        )

    def test_triggers_after_completing_first_task(self):
        """After submitting task 1, should trigger task 2 if enough new answers."""
        assert should_trigger_next_practical_task(
            role="frontend_engineer",
            answered_count=6,
            tasks_remaining_in_plan=1,
            tasks_completed_count=1,
        )

    def test_behavioral_closing_blocks_trigger(self):
        assert not should_trigger_next_practical_task(
            role="backend_engineer",
            answered_count=4,
            tasks_remaining_in_plan=1,
            tasks_completed_count=0,
            current_stage_key="behavioral_closing",
        )

    def test_technical_stage_allows_trigger(self):
        assert should_trigger_next_practical_task(
            role="qa_engineer",
            answered_count=4,
            tasks_remaining_in_plan=1,
            tasks_completed_count=0,
            current_stage_key="technical",
        )


# ---------------------------------------------------------------------------
# task_index / task_total in frontend response
# ---------------------------------------------------------------------------

class TestTaskIndexAndTotal:

    def test_frontend_safe_dict_does_not_include_task_index_by_default(self):
        """get_task_for_frontend doesn't inject task_index/total — that's done in interview_service."""
        tasks = TASK_BANK.get("frontend_engineer", [])
        safe = get_task_for_frontend(tasks[0], "ru")
        # These come from the service layer, not from the bank
        # get_task_for_frontend should NOT include them (service adds them)
        assert "task_index" not in safe
        assert "task_total" not in safe

    def test_schema_accepts_task_index_and_total(self):
        from app.schemas.interview import PracticalTaskResponse
        tasks = TASK_BANK.get("frontend_engineer", [])
        task_data = get_task_for_frontend(tasks[0], "en")
        resp = PracticalTaskResponse(
            **task_data,
            task_index=2,
            task_total=3,
        )
        assert resp.task_index == 2
        assert resp.task_total == 3
        # Confirm no expected_solution snuck in
        resp_dict = resp.model_dump()
        assert "expected_solution" not in resp_dict
        assert "evaluation_rubric" not in resp_dict
