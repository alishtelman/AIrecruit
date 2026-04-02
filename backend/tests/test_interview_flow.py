"""Tests for the full interview flow: upload resume → start → message → finish."""
import asyncio
import io

import pytest
from docx import Document
from httpx import AsyncClient

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
    assert data["question_count"] == 1
    assert data["max_questions"] == 8
    assert data["current_question"]  # non-empty question from AI

    # Answer all 8 questions (Q1 was asked at start, each answer triggers the next)
    # Messages 1-7 answer Q1-Q7 and receive Q2-Q8
    # Message 8 answers Q8 and receives current_question=None
    answer = (
        "Я решил задачу по шагам и потому что это снижало риски, "
        "сначала проверял крайние случаи и только потом двигался дальше."
    )
    for i in range(8):
        resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": answer},
        )
        assert resp.status_code == 200, resp.text
        msg_data = resp.json()
        assert msg_data["status"] == "in_progress"

    # After answering all 8, no more questions
    assert msg_data["question_count"] == 8
    assert msg_data["current_question"] is None

    # Finish
    resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    finish_data = resp.json()
    assert finish_data["status"] == "report_generated"
    assert finish_data["report_id"]
    assert 0 < finish_data["summary"]["overall_score"] <= 10

    # Get interview detail
    resp = await client.get(
        f"/api/v1/interviews/{interview_id}",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["has_report"] is True
    # 8 assistant messages + 8 candidate messages = 16 visible messages
    assert len(detail["messages"]) == 16

    # Get report
    resp = await client.get(
        f"/api/v1/reports/{finish_data['report_id']}",
        headers=auth_headers(candidate_token),
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["hiring_recommendation"] in ("no", "maybe", "yes", "strong_yes")
    assert report["summary_model"]["core_topics"] == 8
    assert report["summary_model"]["total_turns"] >= 8


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
    for _ in range(40):
        status_resp = await client.get(
            f"/api/v1/interviews/{interview_id}/report-status",
            headers=auth_headers(candidate_token),
        )
        assert status_resp.status_code == 200, status_resp.text
        payload = status_resp.json()
        if payload["processing_state"] == "ready":
            ready_payload = payload
            break
        assert payload["processing_state"] in {"pending", "processing"}
        await asyncio.sleep(0.1)

    assert ready_payload is not None
    assert ready_payload["status"] == "report_generated"
    assert ready_payload["report_id"]


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

    first = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "не делал"},
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["question_count"] == 1
    assert first_data["is_followup"] is True

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
    assert second_data["question_count"] == 2
    assert second_data["is_followup"] is False


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

    weak_answer = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "не помню"},
    )
    assert weak_answer.status_code == 200, weak_answer.text
    weak_data = weak_answer.json()
    assert weak_data["question_type"] == "claim_verification"
    assert weak_data["is_followup"] is True
    assert weak_data["question_count"] == 1
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

    first = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Я использовал PostgreSQL, настраивал индексы и смотрел планы запросов через EXPLAIN ANALYZE."},
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["question_type"] in {"verification", "claim_verification", "deep_technical"}

    second = await client.post(
        f"/api/v1/interviews/{interview_id}/message",
        headers=auth_headers(candidate_token),
        json={"message": "Мы строили event-driven сервисы на Kafka и использовали outbox pattern."},
    )
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["question_count"] == 2
    assert second_data["is_followup"] is False


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

    finish = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish.status_code == 200, finish.text
    report_id = finish.json()["report_id"]

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
