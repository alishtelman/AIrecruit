"""Tests for company-owned employee assessments and their access controls."""
import io
import uuid

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


async def _create_assessment(client: AsyncClient, company_token: str, employee_email: str, employee_name: str) -> dict:
    resp = await client.post(
        "/api/v1/company/assessments",
        headers=auth_headers(company_token),
        json={
            "employee_email": employee_email,
            "employee_name": employee_name,
            "target_role": "backend_engineer",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _complete_employee_assessment(client: AsyncClient, token: str, invite_token: str) -> tuple[str, str]:
    start_resp = await client.post(
        f"/api/v1/employee/invite/{invite_token}/start",
        headers=auth_headers(token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 200, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    for i in range(8):
        msg_resp = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(token),
            json={"message": f"Employee assessment answer {i + 1}"},
        )
        assert msg_resp.status_code == 200, msg_resp.text

    finish_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(token),
    )
    assert finish_resp.status_code == 200, finish_resp.text
    return interview_id, finish_resp.json()["report_id"]


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
