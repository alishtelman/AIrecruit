"""Tests for company-owned employee assessments and their access controls."""
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
            json={
                "message": (
                    "I solved the task step by step because that reduced risk, "
                    "validated edge cases first, and then moved to implementation."
                )
            },
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
