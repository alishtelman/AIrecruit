"""Tests for company-owned employee assessments and their access controls."""
import asyncio
import io
import uuid
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


async def _register_candidate(client: AsyncClient, email: str, full_name: str = "Employee User") -> str:
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email,
        "password": "testpass123",
        "full_name": full_name,
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    return resp.json()["access_token"]


async def _register_company(client: AsyncClient, name: str = "Other Corp") -> str:
    email = f"company_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/company/register", json={
        "email": email,
        "password": "testpass123",
        "company_name": name,
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    return resp.json()["access_token"]


async def _upload_resume(client: AsyncClient, token: str) -> None:
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(token),
        files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text


async def _create_template(client: AsyncClient, company_token: str, name: str, target_role: str) -> dict:
    resp = await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": name,
            "target_role": target_role,
            "questions": [
                "Tell us about a project you shipped.",
                "How do you handle feedback?",
            ],
            "is_public": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_assessment(
    client: AsyncClient,
    company_token: str,
    employee_email: str,
    employee_name: str,
    **extra: object,
) -> dict:
    resp = await client.post(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
        json={
            "employee_email": employee_email,
            "employee_name": employee_name,
            "target_role": "backend_engineer",
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _answer_all_questions(
    client: AsyncClient,
    token: str,
    interview_id: str,
    *,
    message: str | None = None,
) -> None:
    answer_text = message or (
        "I solved the task step by step because that reduced risk, "
        "validated edge cases first, and then moved to implementation."
    )
    for _ in range(16):
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(token),
            json={"message": answer_text},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        if msg_resp.json()["current_question"] is None:
            return
    raise AssertionError(f"Interview {interview_id} did not reach a finishable state")


async def _wait_for_report_id(client: AsyncClient, token: str, interview_id: str) -> str:
    report_id = None
    failure_reason = None
    for _ in range(160):
        status_resp = await client.get(
            f"/api/v1/interviews/{interview_id}/report-status",
            headers=auth_headers(token),
        )
        assert status_resp.status_code == 200, status_resp.text
        status_data = status_resp.json()
        if status_data["processing_state"] == "ready" and status_data["report_id"]:
            report_id = status_data["report_id"]
            break
        if status_data["processing_state"] == "failed":
            failure_reason = status_data.get("failure_reason")
            break
        assert status_data["processing_state"] in {"pending", "processing"}
        await asyncio.sleep(0.25)
    assert report_id, failure_reason or f"Report was not ready for interview {interview_id}"
    return report_id


async def _complete_employee_assessment(client: AsyncClient, token: str, invite_token: str) -> tuple[str, str]:
    start_resp = await client.post(
        f"/api/v1/employee/invite/{invite_token}/start",
        headers=auth_headers(token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 200, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    await _answer_all_questions(client, token, interview_id)

    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(token),
    )
    assert finish_resp.status_code == 200, finish_resp.text
    finish_data = finish_resp.json()
    report_id = finish_data.get("report_id")
    if not report_id:
        report_id = await _wait_for_report_id(client, token, interview_id)
    return interview_id, report_id


@pytest.mark.asyncio
async def test_employee_assessment_requires_matching_email(client: AsyncClient, company_token: str):
    assessment = await _create_assessment(
        client,
        company_token,
        employee_email=f"invitee_{uuid.uuid4().hex[:8]}@example.com",
        employee_name="Invited Employee",
    )

    other_candidate_token = await _register_candidate(
        client,
        email=f"other_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Wrong Candidate",
    )

    resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(other_candidate_token),
        json={"language": "en"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_employee_assessment_starts_for_invited_candidate(client: AsyncClient, company_token: str):
    employee_email = f"invitee_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Invited Employee")
    candidate_token = await _register_candidate(client, employee_email, "Invited Employee")
    await _upload_resume(client, candidate_token)

    resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["interview_id"]
    assert data["assessment_id"] == assessment["id"]

    assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert assessments_resp.status_code == 200
    saved = next(a for a in assessments_resp.json() if a["id"] == assessment["id"])
    assert saved["status"] == "in_progress"
    assert saved["module_count"] == 1
    assert saved["current_module_type"] == "adaptive_interview"
    assert saved["module_plan"][0]["status"] == "in_progress"
    assert saved["module_plan"][0]["interview_id"] == data["interview_id"]


@pytest.mark.asyncio
async def test_employee_assessment_invite_returns_module_orchestration_payload(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"inviteview_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(
        client,
        company_token,
        employee_email,
        "Invite View Candidate",
        module_plan=[
            {
                "module_type": "adaptive_interview",
                "title": "Core Interview",
            },
            {
                "module_type": "system_design",
                "title": "System Design",
            },
        ],
    )
    candidate_token = await _register_candidate(client, employee_email, "Invite View Candidate")
    await _upload_resume(client, candidate_token)

    invite_resp = await client.get(f"/api/v1/employee/invite/{assessment['invite_token']}")
    assert invite_resp.status_code == 200, invite_resp.text
    invite = invite_resp.json()
    assert invite["assessment_id"] == assessment["id"]
    assert invite["module_count"] == 2
    assert invite["current_module_index"] == 0
    assert invite["current_module_type"] == "adaptive_interview"
    assert invite["current_module_title"] == "Core Interview"
    assert invite["active_interview_id"] is None
    assert invite["can_start_current_module"] is True
    assert invite["module_plan"][1]["module_type"] == "system_design"

    start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 200, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    refreshed_resp = await client.get(f"/api/v1/employee/invite/{assessment['invite_token']}")
    assert refreshed_resp.status_code == 200, refreshed_resp.text
    refreshed = refreshed_resp.json()
    assert refreshed["status"] == "in_progress"
    assert refreshed["active_interview_id"] == interview_id
    assert refreshed["can_start_current_module"] is False
    assert refreshed["module_plan"][0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_company_ai_proctoring_policy_applies_to_new_assessment_interviews(
    client: AsyncClient,
    company_token: str,
):
    settings_resp = await client.put(
        "/api/v1/company/settings/ai",
        headers=auth_headers(company_token),
        json={"proctoring_policy_mode": "strict_flagging"},
    )
    assert settings_resp.status_code == 200, settings_resp.text

    employee_email = f"strict_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Strict Policy Candidate")
    candidate_token = await _register_candidate(client, employee_email, "Strict Policy Candidate")
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 200, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    signals_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/signals",
        headers=auth_headers(candidate_token),
        json={"paste_count": 1},
    )
    assert signals_resp.status_code == 204, signals_resp.text

    await _answer_all_questions(client, candidate_token, interview_id)
    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish_resp.status_code == 200, finish_resp.text
    report_id = finish_resp.json().get("report_id") or await _wait_for_report_id(client, candidate_token, interview_id)

    timeline_resp = await client.get(
        f"/api/v1/company/reports/{report_id}/proctoring-timeline",
        headers=auth_headers(company_token),
    )
    assert timeline_resp.status_code == 200, timeline_resp.text
    timeline = timeline_resp.json()
    assert timeline["policy_mode"] == "strict_flagging"
    paste_events = [event for event in timeline["events"] if event["event_type"] == "paste_detected"]
    assert paste_events
    assert paste_events[0]["severity"] == "medium"


@pytest.mark.asyncio
async def test_company_ai_model_preference_applies_to_assessment_reports(
    client: AsyncClient,
    company_token: str,
):
    settings_resp = await client.put(
        "/api/v1/company/settings/ai",
        headers=auth_headers(company_token),
        json={"assessor_model_preference": "llama-3.1-8b-instant"},
    )
    assert settings_resp.status_code == 200, settings_resp.text

    employee_email = f"modelpref_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Model Preference Candidate")
    candidate_token = await _register_candidate(client, employee_email, "Model Preference Candidate")
    await _upload_resume(client, candidate_token)

    interview_id, report_id = await _complete_employee_assessment(
        client,
        candidate_token,
        assessment["invite_token"],
    )
    assert interview_id

    report_resp = await client.get(
        f"/api/v1/company/reports/{report_id}",
        headers=auth_headers(company_token),
    )
    assert report_resp.status_code == 200, report_resp.text
    report = report_resp.json()
    assert "llama-3.1-8b-instant" in report["model_version"]


@pytest.mark.asyncio
async def test_employee_assessment_defaults_to_single_adaptive_interview_module(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"defaultmod_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Module Candidate")

    assert assessment["module_count"] == 1
    assert assessment["current_module_index"] == 0
    assert assessment["current_module_type"] == "adaptive_interview"
    assert assessment["module_plan"][0]["module_type"] == "adaptive_interview"
    assert assessment["module_plan"][0]["status"] == "pending"
    assert assessment["module_plan"][0]["interview_id"] is None


@pytest.mark.asyncio
async def test_employee_assessment_accepts_custom_module_plan_and_advances_to_next_module(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"multimod_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(
        client,
        company_token,
        employee_email,
        "Multi Module Candidate",
        module_plan=[
            {
                "module_type": "adaptive_interview",
                "title": "Core Interview",
            },
            {
                "module_id": "system_design_main",
                "module_type": "system_design",
                "title": "Architecture Deep Dive",
                "config": {"duration_minutes": 45},
            },
        ],
    )
    assert assessment["module_count"] == 2
    assert assessment["current_module_index"] == 0
    assert assessment["current_module_type"] == "adaptive_interview"
    assert assessment["module_plan"][1]["module_type"] == "system_design"
    assert assessment["module_plan"][1]["config"]["duration_minutes"] == 45
    assert assessment["module_plan"][1]["config"]["target_role"] == "backend_engineer"

    candidate_token = await _register_candidate(client, employee_email, "Multi Module Candidate")
    await _upload_resume(client, candidate_token)

    first_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert first_start_resp.status_code == 200, first_start_resp.text
    interview_id = first_start_resp.json()["interview_id"]

    second_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert second_start_resp.status_code == 200, second_start_resp.text
    assert second_start_resp.json()["interview_id"] == interview_id

    await _answer_all_questions(client, candidate_token, interview_id)

    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish_resp.status_code == 200, finish_resp.text
    finish_data = finish_resp.json()
    assert finish_data["status"] in {"report_processing", "report_generated"}
    assert finish_data["assessment_progress"] is not None
    assert finish_data["assessment_progress"]["has_remaining_modules"] is True
    assert finish_data["assessment_progress"]["invite_token"] == assessment["invite_token"]
    assert finish_data["assessment_progress"]["current_module_index"] == 1
    assert finish_data["assessment_progress"]["current_module_type"] == "system_design"
    assert finish_data["assessment_progress"]["current_module_title"] == "Architecture Deep Dive"

    status_resp = await client.get(
        f"/api/v1/interviews/{interview_id}/report-status",
        headers=auth_headers(candidate_token),
    )
    assert status_resp.status_code == 200, status_resp.text
    status_data = status_resp.json()
    assert status_data["assessment_progress"] is not None
    assert status_data["assessment_progress"]["has_remaining_modules"] is True

    assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert assessments_resp.status_code == 200, assessments_resp.text
    saved = next(row for row in assessments_resp.json() if row["id"] == assessment["id"])
    assert saved["status"] == "in_progress"
    assert saved["interview_id"] is None
    assert saved["report_id"] is None
    assert saved["completed_at"] is None
    assert saved["current_module_index"] == 1
    assert saved["current_module_type"] == "system_design"
    assert saved["module_plan"][0]["status"] == "completed"
    assert saved["module_plan"][0]["interview_id"] == interview_id
    assert saved["module_plan"][0]["completed_at"] is not None
    assert saved["module_plan"][1]["module_id"] == "system_design_main"
    assert saved["module_plan"][1]["title"] == "Architecture Deep Dive"
    assert saved["module_plan"][1]["status"] == "pending"
    assert saved["module_plan"][1]["config"]["duration_minutes"] == 45

    invite_resp = await client.get(f"/api/v1/employee/invite/{assessment['invite_token']}")
    assert invite_resp.status_code == 200, invite_resp.text
    invite = invite_resp.json()
    assert invite["active_interview_id"] is None
    assert invite["can_start_current_module"] is True
    assert invite["current_module_index"] == 1
    assert invite["current_module_type"] == "system_design"
    assert invite["current_module_title"] == "Architecture Deep Dive"

    system_design_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert system_design_start_resp.status_code == 200, system_design_start_resp.text
    system_design_interview_id = system_design_start_resp.json()["interview_id"]

    detail_resp = await client.get(
        f"/api/v1/interviews/{system_design_interview_id}",
        headers=auth_headers(candidate_token),
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["module_session"] is not None
    assert detail["module_session"]["module_type"] == "system_design"
    assert detail["module_session"]["module_title"] == "Architecture Deep Dive"
    assert detail["module_session"]["scenario_title"]
    assert detail["module_session"]["stage_key"] == "requirements"
    assert detail["module_session"]["stage_count"] == 3

    await _answer_all_questions(client, candidate_token, system_design_interview_id)

    final_finish_resp = await client.post(
        f"/api/v1/interviews/{system_design_interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert final_finish_resp.status_code == 200, final_finish_resp.text
    final_finish_data = final_finish_resp.json()
    assert final_finish_data["assessment_progress"] is not None
    assert final_finish_data["assessment_progress"]["has_remaining_modules"] is False
    final_report_id = final_finish_data.get("report_id")
    if not final_report_id:
        final_report_id = await _wait_for_report_id(client, candidate_token, system_design_interview_id)

    company_report_resp = await client.get(
        f"/api/v1/company/reports/{final_report_id}",
        headers=auth_headers(company_token),
    )
    assert company_report_resp.status_code == 200, company_report_resp.text
    company_report = company_report_resp.json()
    assert company_report["module_session"] is not None
    assert company_report["module_session"]["module_type"] == "system_design"
    assert company_report["module_session"]["scenario_title"]
    assert company_report["system_design_summary"] is not None
    summary = company_report["system_design_summary"]
    assert summary["stage_count"] == 3
    assert summary["overall_score"] is not None
    assert len(summary["rubric_scores"]) == 4
    assert all(item["score"] is not None for item in summary["rubric_scores"])
    assert len(summary["stages"]) == 3
    assert all(stage["stage_title"] for stage in summary["stages"])
    assert all(stage["stage_score"] is not None for stage in summary["stages"])
    assert company_report["per_question_analysis"]
    assert any(item.get("stage_title") for item in company_report["per_question_analysis"])

    completed_assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert completed_assessments_resp.status_code == 200, completed_assessments_resp.text
    completed = next(row for row in completed_assessments_resp.json() if row["id"] == assessment["id"])
    assert completed["status"] == "completed"
    assert completed["interview_id"] == system_design_interview_id
    assert completed["module_plan"][1]["status"] == "completed"
    assert completed["module_plan"][1]["interview_id"] == system_design_interview_id


@pytest.mark.asyncio
async def test_employee_assessment_supports_coding_task_module_and_report_summary(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"codingtask_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(
        client,
        company_token,
        employee_email,
        "Coding Task Candidate",
        module_plan=[
            {
                "module_type": "adaptive_interview",
                "title": "Core Interview",
            },
            {
                "module_id": "coding_task_main",
                "module_type": "coding_task",
                "title": "Coding Task",
                "config": {"scenario_id": "rate_limiter_window_counter"},
            },
        ],
    )
    candidate_token = await _register_candidate(client, employee_email, "Coding Task Candidate")
    await _upload_resume(client, candidate_token)

    first_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert first_start_resp.status_code == 200, first_start_resp.text
    first_interview_id = first_start_resp.json()["interview_id"]
    await _answer_all_questions(client, candidate_token, first_interview_id)

    first_finish_resp = await client.post(
        f"/api/v1/interviews/{first_interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert first_finish_resp.status_code == 200, first_finish_resp.text
    first_finish_data = first_finish_resp.json()
    assert first_finish_data["assessment_progress"] is not None
    assert first_finish_data["assessment_progress"]["has_remaining_modules"] is True
    assert first_finish_data["assessment_progress"]["current_module_type"] == "coding_task"

    coding_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert coding_start_resp.status_code == 200, coding_start_resp.text
    coding_interview_id = coding_start_resp.json()["interview_id"]

    detail_resp = await client.get(
        f"/api/v1/interviews/{coding_interview_id}",
        headers=auth_headers(candidate_token),
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["module_session"] is not None
    assert detail["module_session"]["module_type"] == "coding_task"
    assert detail["module_session"]["module_title"] == "Coding Task"
    assert detail["module_session"]["scenario_title"]
    assert detail["module_session"]["stack_focus"]
    assert detail["module_session"]["preferred_language"] == "python"
    assert detail["module_session"]["workspace_hint"]
    assert detail["module_session"]["stage_key"] == "task_brief"
    assert detail["module_session"]["stage_count"] == 3

    artifact_resp = await client.put(
        f"/api/v1/interviews/{coding_interview_id}/coding-artifact",
        headers=auth_headers(candidate_token),
        json={
            "language": "python",
            "code": """from collections import defaultdict, deque

windows = defaultdict(deque)

def allow_request(user_id: str, now: int, limit: int = 5, window_seconds: int = 60) -> bool:
    queue = windows[user_id]
    while queue and now - queue[0] >= window_seconds:
        queue.popleft()
    if len(queue) >= limit:
        return False
    queue.append(now)
    return True
""",
        },
    )
    assert artifact_resp.status_code == 200, artifact_resp.text
    artifact = artifact_resp.json()
    assert artifact["language"] == "python"
    assert "allow_request" in artifact["code"]
    assert artifact["updated_at"] is not None

    artifact_fetch_resp = await client.get(
        f"/api/v1/interviews/{coding_interview_id}/coding-artifact",
        headers=auth_headers(candidate_token),
    )
    assert artifact_fetch_resp.status_code == 200, artifact_fetch_resp.text
    assert artifact_fetch_resp.json()["code"] == artifact["code"]

    coding_answer = (
        "I would validate user_id and timestamp first, keep a per-user ordered queue, "
        "evict old timestamps before checking the limit, and test edge timestamps, "
        "burst traffic, and invalid input so the per-request cost stays amortized O(1)."
    )
    await _answer_all_questions(
        client,
        candidate_token,
        coding_interview_id,
        message=coding_answer,
    )

    final_finish_resp = await client.post(
        f"/api/v1/interviews/{coding_interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert final_finish_resp.status_code == 200, final_finish_resp.text
    final_finish_data = final_finish_resp.json()
    final_report_id = final_finish_data.get("report_id")
    if not final_report_id:
        final_report_id = await _wait_for_report_id(client, candidate_token, coding_interview_id)

    company_report_resp = await client.get(
        f"/api/v1/company/reports/{final_report_id}",
        headers=auth_headers(company_token),
    )
    assert company_report_resp.status_code == 200, company_report_resp.text
    company_report = company_report_resp.json()
    assert company_report["module_session"] is not None
    assert company_report["module_session"]["module_type"] == "coding_task"
    assert company_report["coding_task_summary"] is not None
    summary = company_report["coding_task_summary"]
    assert summary["stage_count"] == 3
    assert summary["overall_score"] is not None
    assert len(summary["rubric_scores"]) == 7
    assert summary["coverage_score"] is not None
    assert summary["coverage_checks"]
    assert summary["runner_score"] is not None
    assert summary["runner_checks"]
    assert summary["stack_score"] is not None
    assert summary["stack_checks"]
    assert summary["stack_focus"]
    assert summary["preferred_language"] == "python"
    assert summary["has_code_submission"] is True
    assert summary["implementation_excerpt"] is not None
    assert "allow_request" in summary["implementation_excerpt"]
    assert summary["code_signal_score"] is not None
    assert any(check["status"] == "passed" for check in summary["coverage_checks"])
    assert any(check["check_key"] == "expired_window_cleanup" for check in summary["coverage_checks"])
    assert any(check["check_key"] == "runner_blocks_over_limit" for check in summary["runner_checks"])
    assert any(check["status"] == "passed" for check in summary["runner_checks"])
    assert any(check["status"] in {"passed", "partial"} for check in summary["stack_checks"])
    assert len(summary["stages"]) == 3
    assert all(stage["stage_title"] for stage in summary["stages"])
    assert company_report["per_question_analysis"]
    assert any(item.get("stage_title") for item in company_report["per_question_analysis"])

    completed_assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert completed_assessments_resp.status_code == 200, completed_assessments_resp.text
    completed = next(row for row in completed_assessments_resp.json() if row["id"] == assessment["id"])
    assert completed["status"] == "completed"
    assert completed["interview_id"] == coding_interview_id
    assert completed["module_plan"][1]["status"] == "completed"
    assert completed["module_plan"][1]["interview_id"] == coding_interview_id


@pytest.mark.asyncio
async def test_employee_assessment_coding_task_uses_role_specific_stack_profiles(
    client: AsyncClient,
    company_token: str,
):
    cases = [
        (
            "frontend_engineer",
            "typescript",
            "async_search_state_manager",
            "React",
        ),
        (
            "qa_engineer",
            "python",
            "flaky_test_classifier",
            "QA automation",
        ),
    ]

    for target_role, expected_language, expected_scenario_id, expected_stack_marker in cases:
        employee_email = f"{target_role}_{uuid.uuid4().hex[:8]}@example.com"
        assessment = await _create_assessment(
            client,
            company_token,
            employee_email,
            f"{target_role} Candidate",
            target_role=target_role,
            module_plan=[
                {
                    "module_type": "adaptive_interview",
                    "title": "Core Interview",
                },
                {
                    "module_id": "coding_task_main",
                    "module_type": "coding_task",
                    "title": "Coding Task",
                },
            ],
        )
        candidate_token = await _register_candidate(client, employee_email, f"{target_role} Candidate")
        await _upload_resume(client, candidate_token)

        first_start_resp = await client.post(
            f"/api/v1/employee/invite/{assessment['invite_token']}/start",
            headers=auth_headers(candidate_token),
            json={"language": "en"},
        )
        assert first_start_resp.status_code == 200, first_start_resp.text
        first_interview_id = first_start_resp.json()["interview_id"]
        await _answer_all_questions(client, candidate_token, first_interview_id)

        first_finish_resp = await client.post(
            f"/api/v1/interviews/{first_interview_id}/finish",
            headers=auth_headers(candidate_token),
        )
        assert first_finish_resp.status_code == 200, first_finish_resp.text

        coding_start_resp = await client.post(
            f"/api/v1/employee/invite/{assessment['invite_token']}/start",
            headers=auth_headers(candidate_token),
            json={"language": "en"},
        )
        assert coding_start_resp.status_code == 200, coding_start_resp.text
        coding_interview_id = coding_start_resp.json()["interview_id"]

        detail_resp = await client.get(
            f"/api/v1/interviews/{coding_interview_id}",
            headers=auth_headers(candidate_token),
        )
        assert detail_resp.status_code == 200, detail_resp.text
        detail = detail_resp.json()
        assert detail["module_session"] is not None
        assert detail["module_session"]["module_type"] == "coding_task"
        assert detail["module_session"]["scenario_id"] == expected_scenario_id
        assert detail["module_session"]["preferred_language"] == expected_language
        assert expected_stack_marker in detail["module_session"]["stack_focus"]
        assert detail["module_session"]["workspace_hint"]


@pytest.mark.asyncio
async def test_employee_assessment_supports_sql_live_module_and_report_summary(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"sqllive_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(
        client,
        company_token,
        employee_email,
        "SQL Live Candidate",
        module_plan=[
            {
                "module_type": "adaptive_interview",
                "title": "Core Interview",
            },
            {
                "module_id": "sql_live_main",
                "module_type": "sql_live",
                "title": "SQL Live",
                "config": {"scenario_id": "customer_revenue_rollup"},
            },
        ],
    )
    candidate_token = await _register_candidate(client, employee_email, "SQL Live Candidate")
    await _upload_resume(client, candidate_token)

    first_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert first_start_resp.status_code == 200, first_start_resp.text
    first_interview_id = first_start_resp.json()["interview_id"]
    await _answer_all_questions(client, candidate_token, first_interview_id)

    first_finish_resp = await client.post(
        f"/api/v1/interviews/{first_interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert first_finish_resp.status_code == 200, first_finish_resp.text
    first_finish_data = first_finish_resp.json()
    assert first_finish_data["assessment_progress"] is not None
    assert first_finish_data["assessment_progress"]["has_remaining_modules"] is True
    assert first_finish_data["assessment_progress"]["current_module_type"] == "sql_live"

    sql_start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert sql_start_resp.status_code == 200, sql_start_resp.text
    sql_interview_id = sql_start_resp.json()["interview_id"]

    detail_resp = await client.get(
        f"/api/v1/interviews/{sql_interview_id}",
        headers=auth_headers(candidate_token),
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["module_session"] is not None
    assert detail["module_session"]["module_type"] == "sql_live"
    assert detail["module_session"]["stage_key"] == "schema_review"
    assert detail["module_session"]["stage_count"] == 3

    artifact_resp = await client.put(
        f"/api/v1/interviews/{sql_interview_id}/coding-artifact",
        headers=auth_headers(candidate_token),
        json={
            "language": "sql",
            "code": """
SELECT
  c.name AS customer_name,
  COUNT(o.id) AS completed_order_count,
  SUM(o.total_amount) AS completed_revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.is_active = 1
  AND o.status = 'completed'
  AND o.created_at >= '2024-03-01'
  AND o.created_at < '2024-04-01'
GROUP BY c.id, c.name
HAVING SUM(o.total_amount) >= 100
ORDER BY completed_revenue DESC, customer_name ASC
""",
        },
    )
    assert artifact_resp.status_code == 200, artifact_resp.text
    artifact = artifact_resp.json()
    assert artifact["language"] == "sql"
    assert "customer_name" in artifact["code"]

    sql_answer = (
        "I would verify the join cardinality first, make sure only completed March orders are included, "
        "check the aliases against the expected output, and validate the result with a control query per customer "
        "before considering indexes on status, created_at, and customer_id."
    )
    await _answer_all_questions(
        client,
        candidate_token,
        sql_interview_id,
        message=sql_answer,
    )

    final_finish_resp = await client.post(
        f"/api/v1/interviews/{sql_interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert final_finish_resp.status_code == 200, final_finish_resp.text
    final_finish_data = final_finish_resp.json()
    final_report_id = final_finish_data.get("report_id")
    if not final_report_id:
        final_report_id = await _wait_for_report_id(client, candidate_token, sql_interview_id)

    company_report_resp = await client.get(
        f"/api/v1/company/reports/{final_report_id}",
        headers=auth_headers(company_token),
    )
    assert company_report_resp.status_code == 200, company_report_resp.text
    company_report = company_report_resp.json()
    assert company_report["module_session"] is not None
    assert company_report["module_session"]["module_type"] == "sql_live"
    assert company_report["sql_live_summary"] is not None
    summary = company_report["sql_live_summary"]
    assert summary["stage_count"] == 3
    assert summary["overall_score"] is not None
    assert summary["validation_score"] is not None
    assert len(summary["rubric_scores"]) == 4
    assert summary["validation_checks"]
    assert summary["query_excerpt"] is not None
    assert "customer_name" in summary["query_excerpt"]
    assert summary["has_query_submission"] is True
    assert any(check["check_key"] == "expected_rows" for check in summary["validation_checks"])
    assert any(check["status"] == "passed" for check in summary["validation_checks"])
    assert len(summary["stages"]) == 3
    assert all(stage["stage_title"] for stage in summary["stages"])
    assert company_report["per_question_analysis"]
    assert any(item.get("stage_title") for item in company_report["per_question_analysis"])

    completed_assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert completed_assessments_resp.status_code == 200, completed_assessments_resp.text
    completed = next(row for row in completed_assessments_resp.json() if row["id"] == assessment["id"])
    assert completed["status"] == "completed"
    assert completed["interview_id"] == sql_interview_id
    assert completed["module_plan"][1]["status"] == "completed"
    assert completed["module_plan"][1]["interview_id"] == sql_interview_id


@pytest.mark.asyncio
async def test_employee_assessment_rejects_module_plan_without_initial_adaptive_interview(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"invalidmod_{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
        json={
            "employee_email": employee_email,
            "employee_name": "Invalid Module Candidate",
            "target_role": "backend_engineer",
            "module_plan": [
                {
                    "module_type": "system_design",
                    "title": "Architecture First",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "First module must be adaptive_interview" in resp.text


@pytest.mark.asyncio
async def test_private_employee_assessment_stays_private(client: AsyncClient, company_token: str):
    employee_email = f"private_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Private Employee")
    candidate_token = await _register_candidate(client, employee_email, "Private Employee")
    await _upload_resume(client, candidate_token)

    interview_id, report_id = await _complete_employee_assessment(
        client,
        candidate_token,
        assessment["invite_token"],
    )

    owner_report = await client.get(
        f"/api/v1/company/reports/{report_id}",
        headers=auth_headers(company_token),
    )
    assert owner_report.status_code == 200

    owner_replay = await client.get(
        f"/api/v1/company/interviews/{interview_id}/replay",
        headers=auth_headers(company_token),
    )
    assert owner_replay.status_code == 200

    other_company_token = await _register_company(client)

    other_report = await client.get(
        f"/api/v1/company/reports/{report_id}",
        headers=auth_headers(other_company_token),
    )
    assert other_report.status_code == 404

    other_replay = await client.get(
        f"/api/v1/company/interviews/{interview_id}/replay",
        headers=auth_headers(other_company_token),
    )
    assert other_replay.status_code == 404

    candidates_resp = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
    )
    assert candidates_resp.status_code == 200
    emails = {row["email"] for row in candidates_resp.json()}
    assert employee_email not in emails

    assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert assessments_resp.status_code == 200, assessments_resp.text
    saved = next(row for row in assessments_resp.json() if row["id"] == assessment["id"])
    assert saved["status"] == "completed"
    assert saved["module_plan"][0]["status"] == "completed"
    assert saved["module_plan"][0]["interview_id"] == interview_id
    assert saved["module_plan"][0]["completed_at"] is not None


@pytest.mark.asyncio
async def test_company_report_proctoring_timeline_returns_company_scoped_events(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"timeline_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Timeline Candidate")
    candidate_token = await _register_candidate(client, employee_email, "Timeline Candidate")
    await _upload_resume(client, candidate_token)

    interview_id, report_id = await _complete_employee_assessment(
        client,
        candidate_token,
        assessment["invite_token"],
    )

    submit_signals = await client.post(
        f"/api/v1/interviews/{interview_id}/signals",
        headers=auth_headers(candidate_token),
        json={
            "response_times": [{"q": 1, "seconds": 4.2}],
            "paste_count": 1,
            "tab_switches": 2,
            "face_away_pct": 0.41,
            "speech_activity_pct": 0.04,
            "silence_pct": 0.96,
            "long_silence_count": 2,
            "speech_segment_count": 1,
            "policy_mode": "strict_flagging",
            "events": [
                {
                    "event_type": "tab_switch",
                    "severity": "medium",
                    "occurred_at": datetime.utcnow().isoformat(),
                    "source": "client",
                    "details": {"source": "visibilitychange"},
                },
                {
                    "event_type": "face_away_high",
                    "severity": "high",
                    "occurred_at": datetime.utcnow().isoformat(),
                    "source": "client",
                    "details": {"face_away_pct": 0.41},
                },
            ],
        },
    )
    assert submit_signals.status_code == 204, submit_signals.text

    timeline = await client.get(
        f"/api/v1/company/reports/{report_id}/proctoring-timeline",
        headers=auth_headers(company_token),
    )
    assert timeline.status_code == 200, timeline.text
    data = timeline.json()
    assert data["report_id"] == report_id
    assert data["policy_mode"] == "strict_flagging"
    assert data["risk_level"] in {"medium", "high"}
    assert data["speech_activity_pct"] == 0.04
    assert data["silence_pct"] == 0.96
    assert data["long_silence_count"] == 2
    assert data["speech_segment_count"] == 1
    assert data["total_events"] >= 4
    assert any(event["event_type"] == "tab_switch" for event in data["events"])
    assert any(event["event_type"] == "speech_activity_low" for event in data["events"])
    assert any(event["event_type"] == "long_silence" for event in data["events"])


@pytest.mark.asyncio
async def test_company_report_cheat_risk_includes_speech_signal_patterns(
    client: AsyncClient,
    company_token: str,
):
    employee_email = f"speechrisk_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(client, company_token, employee_email, "Speech Risk Candidate")
    candidate_token = await _register_candidate(client, employee_email, "Speech Risk Candidate")
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 200, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    await _answer_all_questions(client, candidate_token, interview_id)

    submit_signals = await client.post(
        f"/api/v1/interviews/{interview_id}/signals",
        headers=auth_headers(candidate_token),
        json={
            "response_times": [{"q": 1, "seconds": 6.5}, {"q": 2, "seconds": 7.1}],
            "paste_count": 2,
            "tab_switches": 2,
            "speech_activity_pct": 0.03,
            "silence_pct": 0.97,
            "long_silence_count": 2,
            "speech_segment_count": 1,
            "policy_mode": "strict_flagging",
        },
    )
    assert submit_signals.status_code == 204, submit_signals.text

    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish_resp.status_code == 200, finish_resp.text
    finish_data = finish_resp.json()
    report_id = finish_data.get("report_id")
    if not report_id:
        report_id = await _wait_for_report_id(client, candidate_token, interview_id)

    company_report_resp = await client.get(
        f"/api/v1/company/reports/{report_id}",
        headers=auth_headers(company_token),
    )
    assert company_report_resp.status_code == 200, company_report_resp.text
    company_report = company_report_resp.json()
    assert company_report["cheat_risk_score"] is not None
    assert company_report["cheat_risk_score"] >= 0.4
    assert company_report["cheat_flags"]
    assert any(
        "speech" in flag.lower() or "silence" in flag.lower()
        for flag in company_report["cheat_flags"]
    )


@pytest.mark.asyncio
async def test_candidate_external_campaign_tracks_branding_template_and_opened_status(
    client: AsyncClient,
    company_token: str,
):
    template = await _create_template(
        client,
        company_token,
        name=f"Frontend Campaign {uuid.uuid4().hex[:6]}",
        target_role="frontend_engineer",
    )
    candidate_email = f"campaign_{uuid.uuid4().hex[:8]}@example.com"
    created = await _create_assessment(
        client,
        company_token,
        employee_email=candidate_email,
        employee_name="Frontend Candidate",
        assessment_type="candidate_external",
        target_role="frontend_engineer",
        template_id=template["template_id"],
        branding_name="Spring Hiring Sprint",
        branding_logo_url="https://example.com/logo.png",
        deadline_at=(datetime.utcnow() + timedelta(days=2)).isoformat(),
    )

    assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert assessments_resp.status_code == 200, assessments_resp.text
    saved = next(row for row in assessments_resp.json() if row["id"] == created["id"])
    assert saved["assessment_type"] == "candidate_external"
    assert saved["template_id"] == template["template_id"]
    assert saved["template_name"] == template["name"]
    assert saved["branding_name"] == "Spring Hiring Sprint"
    assert saved["status"] == "pending"

    invite_resp = await client.get(f"/api/v1/employee/invite/{created['invite_token']}")
    assert invite_resp.status_code == 200, invite_resp.text
    invite = invite_resp.json()
    assert invite["assessment_type"] == "candidate_external"
    assert invite["template_name"] == template["name"]
    assert invite["branding_name"] == "Spring Hiring Sprint"
    assert invite["status"] == "opened"

    assessments_resp = await client.get(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
    )
    assert assessments_resp.status_code == 200, assessments_resp.text
    reopened = next(row for row in assessments_resp.json() if row["id"] == created["id"])
    assert reopened["status"] == "opened"
    assert reopened["opened_at"] is not None


@pytest.mark.asyncio
async def test_assessment_invite_rejects_deadline_passed_campaign(client: AsyncClient, company_token: str):
    employee_email = f"expired_{uuid.uuid4().hex[:8]}@example.com"
    assessment = await _create_assessment(
        client,
        company_token,
        employee_email=employee_email,
        employee_name="Expired Invitee",
        deadline_at=(datetime.utcnow() - timedelta(minutes=5)).isoformat(),
    )
    candidate_token = await _register_candidate(client, employee_email, "Expired Invitee")
    await _upload_resume(client, candidate_token)

    info_resp = await client.get(f"/api/v1/employee/invite/{assessment['invite_token']}")
    assert info_resp.status_code == 200, info_resp.text
    assert info_resp.json()["status"] == "expired"

    start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 410, start_resp.text
