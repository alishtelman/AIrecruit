"""Tests for the full interview flow: upload resume → start → message → finish."""
import asyncio
import io
import json
from pathlib import Path

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.competencies import build_interview_plan
from app.core.config import settings
from app.services.interview_service import _answer_relevance, _is_cross_topic_reuse
from tests.conftest import auth_headers


async def _upload_resume(client: AsyncClient, token: str) -> str:
    """Upload a minimal PDF-like file and return resume_id."""
    # Create a minimal valid PDF
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(token),
        files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["resume_id"]


async def _upload_docx_resume(client: AsyncClient, token: str, paragraphs: list[str]) -> str:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)

    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)

    resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(token),
        files={
            "file": (
                "resume.docx",
                buffer,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["resume_id"]


async def _confirm_interview_start(client: AsyncClient, token: str, interview_id: str) -> dict:
    resp = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(token),
        json={"message": "готов"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["question_count"] == 1
    assert data["current_question"]
    return data


async def _finish_and_wait_report_id(
    client: AsyncClient,
    token: str,
    interview_id: str,
    *,
    max_attempts: int = 120,
    poll_delay_seconds: float = 0.25,
) -> str:
    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(token),
    )
    assert finish_resp.status_code == 200, finish_resp.text
    finish_payload = finish_resp.json()

    if finish_payload.get("status") == "report_generated" and finish_payload.get("report_id"):
        return str(finish_payload["report_id"])

    assert finish_payload.get("status") == "report_processing"

    last_state: str | None = None
    for _ in range(max_attempts):
        status_resp = await client.get(
            f"/api/v1/interviews/{interview_id}/report-status",
            headers=auth_headers(token),
        )
        assert status_resp.status_code == 200, status_resp.text
        payload = status_resp.json()
        last_state = payload.get("processing_state")
        if payload.get("processing_state") == "ready" and payload.get("report_id"):
            return str(payload["report_id"])
        if payload.get("processing_state") == "failed":
            raise AssertionError(
                f"Report generation failed: {payload.get('failure_reason') or 'unknown reason'}"
            )
        assert payload.get("processing_state") in {"pending", "processing"}
        await asyncio.sleep(poll_delay_seconds)

    raise AssertionError(f"Timed out waiting for report generation (last_state={last_state})")


async def _wait_for_ready_report_id(
    client: AsyncClient,
    token: str,
    interview_id: str,
    *,
    max_attempts: int = 120,
    poll_delay_seconds: float = 0.25,
) -> str:
    last_state: str | None = None
    for _ in range(max_attempts):
        status_resp = await client.get(
            f"/api/v1/interviews/{interview_id}/report-status",
            headers=auth_headers(token),
        )
        assert status_resp.status_code == 200, status_resp.text
        payload = status_resp.json()
        last_state = payload.get("processing_state")
        if payload.get("processing_state") == "ready" and payload.get("report_id"):
            return str(payload["report_id"])
        if payload.get("processing_state") == "failed":
            raise AssertionError(
                f"Report generation failed: {payload.get('failure_reason') or 'unknown reason'}"
            )
        await asyncio.sleep(poll_delay_seconds)

    raise AssertionError(f"Timed out waiting for report generation (last_state={last_state})")


async def _force_report_status(
    interview_id: str,
    *,
    status: str,
    diagnostics: dict | None,
) -> None:
    state_payload = {"report_diagnostics": diagnostics} if diagnostics is not None else {}
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            if status != "report_generated":
                await session.execute(
                    text(
                        """
                        DELETE FROM assessment_reports
                        WHERE interview_id = CAST(:interview_id AS uuid)
                        """
                    ),
                    {"interview_id": interview_id},
                )
            result = await session.execute(
                text(
                    """
                    UPDATE interviews
                    SET status = :status,
                        interview_state = CAST(:state_json AS jsonb)
                    WHERE id = CAST(:interview_id AS uuid)
                    """
                ),
                {
                    "status": status,
                    "state_json": json.dumps(state_payload),
                    "interview_id": interview_id,
                },
            )
            assert result.rowcount == 1
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_stats_empty(client: AsyncClient, candidate_token: str):
    resp = await client.get(
        "/api/v1/candidate/stats",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_resume"] is False
    assert data["interview_count"] == 0


@pytest.mark.asyncio
async def test_resume_upload_and_profile(client: AsyncClient, candidate_token: str):
    resume_id = await _upload_resume(client, candidate_token)
    assert resume_id

    # Check resume endpoint
    resp = await client.get(
        "/api/v1/candidate/resume",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_name"] == "resume.pdf"
    assert data["file_size"] > 0


@pytest.mark.asyncio
async def test_start_interview_no_resume(client: AsyncClient, candidate_token: str):
    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert resp.status_code == 422  # no resume


@pytest.mark.asyncio
async def test_start_interview_persists_seniority_level(client: AsyncClient, candidate_token: str):
    await _upload_resume(client, candidate_token)

    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "seniority_level": "junior"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["seniority_level"] == "junior"

    interview_id = data["interview_id"]
    detail_resp = await client.get(
        f"/api/v1/interviews/{interview_id}",
        headers=auth_headers(candidate_token),
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["seniority_level"] == "junior"


@pytest.mark.asyncio
async def test_full_interview_flow(client: AsyncClient, candidate_token: str):
    """Start → answer 8 questions → finish → get report."""
    await _upload_resume(client, candidate_token)

    # Start
    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert resp.status_code == 201
    data = resp.json()
    interview_id = data["interview_id"]
    assert data["status"] == "in_progress"
    assert data["question_count"] == 0
    assert data["max_questions"] == 8
    assert data["current_question"]  # intro from AI HR before first question
    assert "готов" in data["current_question"].lower()
    first_question = await _confirm_interview_start(client, candidate_token, interview_id)
    assert first_question["question_count"] == 1

    answers = [
        "Я проектировал backend API, разбивал задачу на этапы, проверял риски через метрики и фиксировал результат в production.",
        "В одном кейсе я оптимизировал PostgreSQL-запросы: смотрел EXPLAIN ANALYZE, менял индексы и контролировал p95 latency.",
        "Для event-driven сервиса я отвечал за контракт сообщений, ретраи, идемпотентность и мониторинг ошибок после релиза.",
        "Когда возник incident, я проверил логи, метрики, гипотезы по последнему релизу и согласовал rollback plan с командой.",
        "Я объяснял бизнесу технический риск простыми терминами: impact, сроки восстановления, workaround и следующий контрольный шаг.",
        "По безопасности я проверял права доступа, обработку секретов, input validation и аудит критичных операций.",
        "С командой я проводил postmortem, выделял root cause, action items и затем проверял, что повторяемость инцидента снизилась.",
        "В финале я связывал техническое решение с метрикой: latency, error rate, throughput и пользовательский impact.",
    ]
    msg_data = first_question
    for i in range(24):
        resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answers[i % len(answers)]},
        )
        assert resp.status_code == 200, resp.text
        msg_data = resp.json()
        assert msg_data["status"] == "in_progress"
        if msg_data["current_question"] is None:
            break

    assert msg_data["question_count"] == 8
    assert msg_data["current_question"] is None

    # Finish
    report_id = await _finish_and_wait_report_id(client, candidate_token, interview_id)

    # Get interview detail
    resp = await client.get(
        f"/api/v1/interviews/{interview_id}",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["has_report"] is True
    # Intro + core questions + adaptive follow-ups are visible; system messages stay hidden.
    assert len(detail["messages"]) >= 17
    assert all(item["role"] != "system" for item in detail["messages"])

    # Get report
    resp = await client.get(
        f"/api/v1/reports/{report_id}",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["hiring_recommendation"] in ("no", "maybe", "yes", "strong_yes")
    if report.get("summary_model"):
        assert report["summary_model"]["core_topics"] == 8
        assert report["summary_model"]["total_turns"] >= 8
    assert report["development_roadmap"] is not None
    assert report["development_roadmap"]["phases"]


@pytest.mark.asyncio
async def test_report_status_endpoint_returns_ready_after_finish(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    answer = (
        "Я декомпозировал задачу, валидировал гипотезы через метрики, "
        "а затем внедрял изменения с контролем рисков и обратной связью."
    )
    while True:
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answer},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        if msg_resp.json()["current_question"] is None:
            break

    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish_resp.status_code == 200, finish_resp.text

    ready_payload = None
    for _ in range(120):
        status_resp = await client.get(
            f"/api/v1/interviews/{interview_id}/report-status",
            headers=auth_headers(candidate_token),
        )
        assert status_resp.status_code == 200, status_resp.text
        payload = status_resp.json()
        if payload["processing_state"] == "ready":
            ready_payload = payload
            break
        if payload["processing_state"] == "failed":
            raise AssertionError("Report generation failed")
        assert payload["processing_state"] in {"pending", "processing"}
        await asyncio.sleep(0.25)

    assert ready_payload is not None
    assert ready_payload["status"] == "report_generated"
    assert ready_payload["report_id"]
    assert ready_payload.get("failure_reason") in (None, "")
    diagnostics = ready_payload.get("diagnostics")
    assert diagnostics is not None
    assert diagnostics.get("last_status") == "ready"
    assert diagnostics.get("attempt_count", 0) >= 1


@pytest.mark.asyncio
async def test_report_retry_requires_completed_interview(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    retry_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/report-retry",
        headers=auth_headers(candidate_token),
    )
    assert retry_resp.status_code == 409, retry_resp.text


@pytest.mark.asyncio
async def test_report_retry_returns_ready_when_report_already_exists(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    answer = (
        "Я проектировал API, оптимизировал запросы, настраивал метрики и работал с PostgreSQL "
        "в production под высокой нагрузкой."
    )
    while True:
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answer},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        if msg_resp.json()["current_question"] is None:
            break

    report_id = await _finish_and_wait_report_id(client, candidate_token, interview_id)

    retry_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/report-retry",
        headers=auth_headers(candidate_token),
    )
    assert retry_resp.status_code == 200, retry_resp.text
    payload = retry_resp.json()
    assert payload["processing_state"] == "ready"
    assert payload["report_id"] == report_id


@pytest.mark.asyncio
async def test_report_status_transition_processing_failed_retry_ready(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    answer = "Я проектировал backend API, оптимизировал SQL-запросы и работал с PostgreSQL."
    while True:
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answer},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        if msg_resp.json()["current_question"] is None:
            break

    await _force_report_status(
        interview_id,
        status="report_processing",
        diagnostics={
            "attempt_count": 1,
            "max_attempts": 3,
            "last_phase": "async_worker_attempt_1",
            "last_status": "processing",
            "last_transition_at": "2026-01-01T00:00:00",
        },
    )
    processing_status = await client.get(
        f"/api/v1/interviews/{interview_id}/report-status",
        headers=auth_headers(candidate_token),
    )
    assert processing_status.status_code == 200, processing_status.text
    assert processing_status.json()["processing_state"] == "processing"

    await _force_report_status(
        interview_id,
        status="failed",
        diagnostics={
            "attempt_count": 2,
            "max_attempts": 3,
            "last_phase": "async_worker_attempt_2",
            "last_status": "failed",
            "last_error": "synthetic provider failure",
            "last_error_at": "2026-01-01T00:00:01",
            "last_transition_at": "2026-01-01T00:00:01",
        },
    )
    failed_status = await client.get(
        f"/api/v1/interviews/{interview_id}/report-status",
        headers=auth_headers(candidate_token),
    )
    assert failed_status.status_code == 200, failed_status.text
    failed_payload = failed_status.json()
    assert failed_payload["processing_state"] == "failed"
    assert failed_payload.get("failure_reason")

    retry_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/report-retry",
        headers=auth_headers(candidate_token),
    )
    assert retry_resp.status_code == 200, retry_resp.text
    retry_payload = retry_resp.json()
    assert retry_payload["processing_state"] in {"processing", "ready"}

    if retry_payload["processing_state"] == "ready" and retry_payload.get("report_id"):
        report_id = retry_payload["report_id"]
    else:
        report_id = await _wait_for_ready_report_id(client, candidate_token, interview_id)
    assert report_id


@pytest.mark.asyncio
async def test_concurrent_report_retry_requests_are_idempotent(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    answer = "Я проектировал API, работал с индексацией PostgreSQL и мониторингом производительности."
    while True:
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answer},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        if msg_resp.json()["current_question"] is None:
            break

    await _force_report_status(
        interview_id,
        status="failed",
        diagnostics={
            "attempt_count": 1,
            "max_attempts": 3,
            "last_phase": "async_worker_attempt_1",
            "last_status": "failed",
            "last_error": "synthetic failure for retry race test",
            "last_error_at": "2026-01-01T00:00:01",
            "last_transition_at": "2026-01-01T00:00:01",
        },
    )

    retry_path = f"/api/v1/interviews/{interview_id}/report-retry"
    retry_one, retry_two = await asyncio.gather(
        client.post(retry_path, headers=auth_headers(candidate_token)),
        client.post(retry_path, headers=auth_headers(candidate_token)),
    )
    assert retry_one.status_code == 200, retry_one.text
    assert retry_two.status_code == 200, retry_two.text

    attempts = [
        retry_one.json().get("diagnostics", {}).get("attempt_count", 0),
        retry_two.json().get("diagnostics", {}).get("attempt_count", 0),
    ]
    assert max(attempts) <= 2
    assert min(attempts) >= 1

    report_id = await _wait_for_ready_report_id(client, candidate_token, interview_id)
    assert report_id


@pytest.mark.asyncio
async def test_dynamic_question_budget_scales_for_rich_resume(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Senior backend engineer with 9 years of experience in high-load systems.",
            "Led migration from monolith to microservices with PostgreSQL, Kafka, Redis and Kubernetes.",
            "Designed gRPC APIs, improved p95 latency by 37%, and reduced incident rate by 42%.",
            "Built observability with tracing and alerting, mentored a team of 6 engineers.",
            "Implemented blue-green deployments and disaster recovery runbooks for production.",
        ],
    )

    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert 20 <= data["max_questions"] <= 40


@pytest.mark.asyncio
async def test_dynamic_question_budget_early_stops_weak_session(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Backend engineer with 8 years of experience in distributed systems.",
            "Worked with PostgreSQL, Kafka, Redis, Docker and Kubernetes in production.",
            "Built API services for high traffic products and incident response playbooks.",
        ],
    )

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    start_data = start_resp.json()
    assert start_data["max_questions"] >= 10

    interview_id = start_data["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)
    terminal_response = None

    for _ in range(14):
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": "не знаю, не делал, не могу объяснить"},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        terminal_response = msg_resp.json()
        if terminal_response["current_question"] is None:
            break

    assert terminal_response is not None
    assert terminal_response["current_question"] is None
    assert terminal_response["max_questions"] == terminal_response["question_count"]
    assert terminal_response["question_count"] <= 10
    assert terminal_response["interview_stage"]["phase_key"] == "behavioral_closing"


def test_build_interview_plan_marks_intro_and_behavioral_closing_phases():
    plan = build_interview_plan(
        "backend_engineer",
        8,
        {
            "project_highlights": ["Migrated a monolith to event-driven services"],
            "verification_targets": ["postgresql", "kafka"],
        },
        structured_flow=True,
    )
    assert plan[0]["phase"] == "intro"
    assert plan[1]["phase"] == "resume_followup"
    assert all(item["phase"] == "technical" for item in plan[2:-1])
    assert plan[-1]["phase"] == "behavioral_closing"


@pytest.mark.parametrize(
    ("role", "expected_resume_competency", "expected_first_technical_competency"),
    [
        ("backend_engineer", "API Design & Protocols", "Database Design & Optimization"),
        ("frontend_engineer", "UI Framework Mastery", "Web Performance Optimization"),
        ("qa_engineer", "Domain & Product Understanding", "Test Strategy & Planning"),
        ("devops_engineer", "CI/CD Pipeline Design", "Security & Compliance"),
        ("data_scientist", "Domain Knowledge Application", "Data Processing & Feature Engineering"),
        ("product_manager", "Requirements & User Research", "Prioritization & Decision Making"),
        ("mobile_engineer", "Platform-Specific Development", "Performance & Memory Optimization"),
        ("designer", "UX Research & User Understanding", "Information Architecture"),
    ],
)
def test_build_interview_plan_uses_strict_role_order_blocks(
    role: str,
    expected_resume_competency: str,
    expected_first_technical_competency: str,
):
    plan = build_interview_plan(
        role,
        8,
        {
            "project_highlights": ["Sample project anchor"],
            "verification_targets": [],
        },
        structured_flow=True,
    )

    assert plan[0]["phase"] == "intro"
    assert plan[1]["phase"] == "resume_followup"
    assert plan[2]["phase"] == "technical"
    assert plan[-1]["phase"] == "behavioral_closing"
    assert plan[1]["competencies"][0] == expected_resume_competency
    assert plan[2]["competencies"][0] == expected_first_technical_competency


def test_role_question_banks_config_drives_resume_and_first_technical_slots():
    banks_path = Path(__file__).resolve().parents[1] / "app" / "ai" / "role_question_banks.json"
    with banks_path.open("r", encoding="utf-8") as handle:
        banks = json.load(handle)

    assert isinstance(banks, dict)
    for role, role_entry in banks.items():
        assert isinstance(role_entry, dict)
        order = role_entry.get("core_competency_order")
        assert isinstance(order, list)
        assert len(order) >= 2

        plan = build_interview_plan(
            role,
            8,
            {"project_highlights": ["Sample project anchor"], "verification_targets": []},
            structured_flow=True,
        )
        assert plan[1]["competencies"][0] == order[0]
        assert plan[2]["competencies"][0] == order[1]
        assert plan[0]["block"] == "intro"
        assert plan[1]["block"] == "resume_followup"
        assert plan[-1]["block"] == "behavioral_closing"
        for slot in plan:
            assert isinstance(slot.get("tier"), str)
            assert isinstance(slot.get("lead_question"), str)
            assert isinstance(slot.get("allowed_probes"), list)
            assert isinstance(slot.get("scored_metrics"), list)
            assert slot["scored_metrics"]


def test_build_interview_plan_reserves_first_resume_anchor_for_resume_followup_slot():
    plan = build_interview_plan(
        "qa_engineer",
        8,
        {
            "project_highlights": [
                "Кейс A: автоматизировал регрессию и снизил дефекты.",
                "Кейс B: внедрил мониторинг критичных сценариев.",
            ],
            "verification_targets": ["postgresql", "docker"],
        },
        structured_flow=True,
    )

    assert plan[0]["phase"] == "intro"
    assert plan[0]["resume_anchor"] is None
    assert plan[1]["phase"] == "resume_followup"
    assert plan[1]["resume_anchor"] == "Кейс A: автоматизировал регрессию и снизил дефекты."


def test_build_interview_plan_for_qa_filters_db_verification_targets_from_resume_profile():
    plan = build_interview_plan(
        "qa_engineer",
        8,
        {
            "project_highlights": [
                "Проводил тест-стратегию для мобильных релизов и дефект-триаж.",
                "Настроил регрессионный набор для критичных платежных сценариев.",
            ],
            "verification_targets": ["postgresql", "redis", "kafka", "graphql"],
        },
        structured_flow=True,
    )

    assigned_targets = [str(item.get("verification_target") or "").lower() for item in plan]

    assert "postgresql" not in assigned_targets
    assert "redis" not in assigned_targets
    assert "kafka" not in assigned_targets


@pytest.mark.asyncio
async def test_interview_starts_with_self_intro_and_moves_to_resume_followup(
    client: AsyncClient,
    candidate_token: str,
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Backend engineer with 7 years of experience in high-load systems.",
            "Led migration from monolith to event-driven services with PostgreSQL and Kafka.",
            "Owned backend APIs, incident response, and performance improvements for production systems.",
        ],
    )

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    start_data = start_resp.json()
    intro_message = start_data["current_question"].lower()
    assert start_data["question_count"] == 0
    assert "ai hr" in intro_message
    assert "готов" in intro_message
    assert start_data["interview_stage"]["phase_key"] == "intro"
    assert start_data["interview_stage"]["slot_number"] == 1
    assert start_data["interview_stage"]["slot_count"] >= 3

    interview_id = start_data["interview_id"]
    ready_data = await _confirm_interview_start(client, candidate_token, interview_id)
    first_question = ready_data["current_question"].lower()
    assert (
        "расскажите о себе" in first_question
        or ("резюме" in first_question and "роль" in first_question)
        or ("опыт" in first_question and "релевант" in first_question)
    )
    assert ready_data["interview_stage"]["phase_key"] == "intro"
    assert ready_data["interview_stage"]["slot_number"] == 1

    next_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={
            "message": (
                "Я backend-инженер, последние годы занимался highload-сервисами, "
                "отвечал за API, миграцию на event-driven архитектуру и production-стабильность."
            )
        },
    )
    assert next_resp.status_code == 200, next_resp.text
    next_data = next_resp.json()
    assert next_data["question_count"] >= 1
    assert next_data["current_question"]
    assert next_data["question_type"] in {"main", "followup", "verification", "claim_verification"}
    if next_data["is_followup"]:
        assert next_data["question_count"] == 1
        assert next_data["interview_stage"]["phase_key"] == "intro"
    else:
        assert next_data["question_count"] == 2
        assert next_data["interview_stage"]["phase_key"] == "resume_followup"
        assert next_data["interview_stage"]["slot_number"] == 2
        assert next_data["interview_stage"]["resume_anchor"]

@pytest.mark.asyncio
async def test_honest_no_experience_causes_single_reframe_then_moves_on(
    client: AsyncClient, candidate_token: str
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    first = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "не делал"},
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["question_count"] >= 1
    assert first_data["current_question"]

    second = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={
            "message": (
                "Я бы подошёл через декомпозицию задачи, оценил риски и потому что "
                "сначала важно понять ограничения, начал бы с простого решения."
            )
        },
    )
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["question_count"] >= first_data["question_count"]
    assert second_data["current_question"]


@pytest.mark.asyncio
async def test_clarification_request_rephrases_once_then_advances_topic(
    client: AsyncClient, candidate_token: str
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "qa_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    intro_answer = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Я работаю в тестировании мобильного приложения и отвечаю за контроль качества."},
    )
    assert intro_answer.status_code == 200, intro_answer.text
    assert intro_answer.json()["question_count"] == 2

    clarification_once = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "не понял"},
    )
    assert clarification_once.status_code == 200, clarification_once.text
    clarification_once_data = clarification_once.json()
    assert clarification_once_data["question_type"] == "clarification"
    assert clarification_once_data["is_followup"] is True
    assert clarification_once_data["question_count"] == 2

    clarification_twice = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "не понял"},
    )
    assert clarification_twice.status_code == 200, clarification_twice.text
    clarification_twice_data = clarification_twice.json()
    assert clarification_twice_data["question_type"] == "main"
    assert clarification_twice_data["is_followup"] is False
    assert clarification_twice_data["question_count"] == 3


@pytest.mark.asyncio
async def test_move_on_request_advances_topic_without_followup_loop(
    client: AsyncClient, candidate_token: str
):
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    intro_answer = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Я работал с backend API, сопровождал сервисы и решал инциденты в production."},
    )
    assert intro_answer.status_code == 200, intro_answer.text
    assert intro_answer.json()["question_count"] == 2

    move_on = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "На этот вопрос уже отвечал, давайте дальше."},
    )
    assert move_on.status_code == 200, move_on.text
    move_on_data = move_on.json()
    assert move_on_data["question_type"] == "main"
    assert move_on_data["is_followup"] is False
    assert move_on_data["question_count"] == 3


@pytest.mark.asyncio
async def test_resume_claim_verification_branch_triggers_for_weak_answer(
    client: AsyncClient, candidate_token: str
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Backend engineer with Python, Kafka, PostgreSQL and Docker experience.",
            "Built event-driven services with Kafka and optimized PostgreSQL queries.",
        ],
    )

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    intro_answer = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Я backend-инженер, строил сервисы и отвечал за production API."},
    )
    assert intro_answer.status_code == 200, intro_answer.text
    assert intro_answer.json()["question_count"] == 2

    weak_answer = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "не помню"},
    )
    assert weak_answer.status_code == 200, weak_answer.text
    weak_data = weak_answer.json()
    assert weak_data["question_type"] == "claim_verification"
    assert weak_data["is_followup"] is True
    assert weak_data["question_count"] == 2
    assert any(
        tech in (weak_data["current_question"] or "").lower()
        for tech in ("kafka", "postgresql", "docker")
    )


def test_answer_relevance_detects_off_topic_verification_answer():
    relevance = _answer_relevance(
        question="Ты упомянул PostgreSQL — как использовал EXPLAIN ANALYZE и индексы?",
        answer="Мы строили event-driven сервисы на Kafka и использовали outbox pattern.",
        new_techs={"kafka"},
        current_claim_target="postgresql",
    )
    assert relevance == "low"


def test_cross_topic_reuse_detects_same_answer_on_new_topic():
    reused = _is_cross_topic_reuse(
        "Я проектировал event-driven сервисы с Kafka, Redis и outbox pattern для highload задач.",
        [
            {
                "content": "Я проектировал event-driven сервисы с Kafka, Redis и outbox pattern для highload задач.",
                "topic_index": 0,
            }
        ],
        1,
    )
    assert reused is True


def test_answer_relevance_keeps_transferred_experience_when_topic_is_still_related():
    relevance = _answer_relevance(
        question="Опишите ваш опыт с асинхронными или событийно-ориентированными архитектурами.",
        answer="Мы строили event-driven сервисы на Kafka, использовали outbox pattern и idempotent consumers.",
        new_techs={"kafka"},
        current_claim_target="kafka",
    )
    assert relevance == "high"


@pytest.mark.asyncio
async def test_low_relevance_after_claim_verification_closes_topic(
    client: AsyncClient, candidate_token: str
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Backend engineer with PostgreSQL, Kafka, Redis and Docker experience.",
            "Optimized PostgreSQL queries and built event-driven services with Kafka.",
        ],
    )

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    first = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Я backend-инженер, много работал с production API и data-intensive сервисами."},
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["question_count"] == 2
    assert first_data["question_type"] == "main"

    second = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Я использовал PostgreSQL, настраивал индексы и смотрел планы запросов через EXPLAIN ANALYZE."},
    )
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["question_type"] in {"verification", "claim_verification", "deep_technical"}

    third = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Мы строили event-driven сервисы на Kafka и использовали outbox pattern."},
    )
    assert third.status_code == 200, third.text
    third_data = third.json()
    assert third_data["question_count"] == 3
    assert third_data["is_followup"] is False


@pytest.mark.asyncio
async def test_reused_cross_topic_answer_moves_to_next_topic(
    client: AsyncClient, candidate_token: str
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Backend engineer with PostgreSQL, Kafka, Redis and Docker experience.",
            "Designed event-driven services and optimized PostgreSQL workloads.",
        ],
    )

    start_resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start_resp.status_code == 201, start_resp.text
    interview_id = start_resp.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    first_answer = (
        "Я проектировал event-driven сервисы, использовал Kafka и PostgreSQL, "
        "смотрел планы запросов и оптимизировал индексы под production-нагрузку."
    )
    first = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": first_answer},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "В PostgreSQL я анализировал query plan, проверял индексы и искал узкие места."},
    )
    assert second.status_code == 200, second.text
    assert second.json()["question_count"] == 2

    third = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": first_answer},
    )
    assert third.status_code == 200, third.text
    third_data = third.json()
    assert third_data["question_count"] == 3
    assert third_data["is_followup"] is False


@pytest.mark.asyncio
async def test_weak_answers_do_not_produce_strong_yes_recommendation(
    client: AsyncClient, candidate_token: str
):
    await _upload_docx_resume(
        client,
        candidate_token,
        [
            "Backend engineer with Python, Kafka, PostgreSQL and Docker experience.",
            "Worked with event-driven services and production jobs.",
        ],
    )

    start = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert start.status_code == 201, start.text
    interview_id = start.json()["interview_id"]
    await _confirm_interview_start(client, candidate_token, interview_id)

    weak_answers = ["все четко", "не помню", "нет опыта", "никак", "не знаю", "нет", "обычно", "не могу", "не делал", "не помню"]
    idx = 0
    while True:
        answer = weak_answers[idx] if idx < len(weak_answers) else weak_answers[-1]
        idx += 1
        msg = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answer},
        )
        assert msg.status_code == 200, msg.text
        if msg.json()["current_question"] is None:
            break
        assert idx < 32

    report_id = await _finish_and_wait_report_id(client, candidate_token, interview_id)

    report = await client.get(
        f"/api/v1/reports/{report_id}",
        headers=auth_headers(candidate_token),
    )
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["hiring_recommendation"] in ("no", "maybe")
    assert data["overall_score"] <= 6.0
    assert data["summary_model"]["topic_outcomes"]
    assert any(
        item["outcome"] in {"honest_gap", "unverified_claim", "evasive"}
        for item in data["summary_model"]["topic_outcomes"]
    )


@pytest.mark.asyncio
async def test_list_interviews(client: AsyncClient, candidate_token: str):
    await _upload_resume(client, candidate_token)

    # Start two interviews
    for role in ("backend_engineer", "frontend_engineer"):
        await client.post(
            "/api/v1/interviews/start",
            headers=auth_headers(candidate_token),
            json={"target_role": role},
        )

    resp = await client.get(
        "/api/v1/interviews/",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 2


@pytest.mark.asyncio
async def test_cannot_finish_early(client: AsyncClient, candidate_token: str):
    await _upload_resume(client, candidate_token)

    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "qa_engineer"},
    )
    interview_id = resp.json()["interview_id"]

    # Try to finish after only 1 question
    resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_send_empty_message(client: AsyncClient, candidate_token: str):
    await _upload_resume(client, candidate_token)

    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    interview_id = resp.json()["interview_id"]

    resp = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "   "},
    )
    assert resp.status_code == 422
