"""Tests for the full interview flow: upload resume → start → message → finish."""
import io

import pytest
from httpx import AsyncClient

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
    for i in range(8):
        resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": f"My answer to question {i+1}"},
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
    assert report["hiring_recommendation"] == "yes"


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
