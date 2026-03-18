"""Tests for company collaboration roles, notes, and activity log."""
import io
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


async def _upload_resume(client: AsyncClient, token: str) -> None:
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(token),
        files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text


async def _complete_interview(client: AsyncClient, token: str, role: str = "backend_engineer") -> dict:
    await _upload_resume(client, token)
    start = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(token),
        json={"target_role": role},
    )
    assert start.status_code == 201, start.text
    interview_id = start.json()["interview_id"]

    for i in range(8):
        msg = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(token),
            json={"message": f"My answer {i + 1}"},
        )
        assert msg.status_code == 200, msg.text

    finish = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(token),
    )
    assert finish.status_code == 200, finish.text
    return finish.json()


async def _candidate_profile(client: AsyncClient, token: str) -> dict:
    resp = await client.get("/api/v1/auth/me/candidate", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["candidate"]


async def _invite_and_login_member(
    client: AsyncClient,
    company_token: str,
    role: str,
) -> tuple[str, str]:
    email = f"{role}_{uuid.uuid4().hex[:8]}@example.com"
    invite = await client.post(
        "/api/v1/company/members/invite",
        headers=auth_headers(company_token),
        json={"email": email, "role": role},
    )
    assert invite.status_code == 201, invite.text
    temp_password = invite.json()["temp_password"]
    assert temp_password

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": temp_password},
    )
    assert login.status_code == 200, login.text
    return email, login.json()["access_token"]


@pytest.mark.asyncio
async def test_recruiter_and_viewer_roles_are_enforced(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
):
    finish = await _complete_interview(client, candidate_token)
    candidate = await _candidate_profile(client, candidate_token)
    candidate_id = candidate["id"]
    report_id = finish["report_id"]

    recruiter_email, recruiter_token = await _invite_and_login_member(client, company_token, "recruiter")
    viewer_email, viewer_token = await _invite_and_login_member(client, company_token, "viewer")

    recruiter_me = await client.get("/api/v1/auth/me", headers=auth_headers(recruiter_token))
    assert recruiter_me.status_code == 200, recruiter_me.text
    assert recruiter_me.json()["company_member_role"] == "recruiter"

    viewer_me = await client.get("/api/v1/auth/me", headers=auth_headers(viewer_token))
    assert viewer_me.status_code == 200, viewer_me.text
    assert viewer_me.json()["company_member_role"] == "viewer"

    shortlist = await client.post(
        "/api/v1/company/shortlists",
        headers=auth_headers(recruiter_token),
        json={"name": f"Team Finalists {uuid.uuid4().hex[:6]}"},
    )
    assert shortlist.status_code == 201, shortlist.text
    shortlist_id = shortlist.json()["shortlist_id"]

    add = await client.post(
        f"/api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id}",
        headers=auth_headers(recruiter_token),
    )
    assert add.status_code == 204, add.text

    outcome = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/outcome",
        headers=auth_headers(recruiter_token),
        json={"outcome": "interviewing", "notes": "Move to final round"},
    )
    assert outcome.status_code == 200, outcome.text

    note = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/notes",
        headers=auth_headers(recruiter_token),
        json={"body": "Shared note from recruiter"},
    )
    assert note.status_code == 201, note.text
    assert note.json()["author_email"] == recruiter_email

    viewer_candidates = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(viewer_token),
    )
    assert viewer_candidates.status_code == 200, viewer_candidates.text

    viewer_notes = await client.get(
        f"/api/v1/company/candidates/{candidate_id}/notes",
        headers=auth_headers(viewer_token),
    )
    assert viewer_notes.status_code == 200, viewer_notes.text
    assert viewer_notes.json()[0]["body"] == "Shared note from recruiter"

    viewer_activity = await client.get(
        f"/api/v1/company/candidates/{candidate_id}/activity",
        headers=auth_headers(viewer_token),
    )
    assert viewer_activity.status_code == 200, viewer_activity.text
    activity_types = {item["activity_type"] for item in viewer_activity.json()}
    assert {"shortlist_added", "outcome_set", "note_added"} <= activity_types

    viewer_shortlist_create = await client.post(
        "/api/v1/company/shortlists",
        headers=auth_headers(viewer_token),
        json={"name": f"Blocked {uuid.uuid4().hex[:4]}"},
    )
    assert viewer_shortlist_create.status_code == 403

    viewer_note_create = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/notes",
        headers=auth_headers(viewer_token),
        json={"body": "Viewer should not write"},
    )
    assert viewer_note_create.status_code == 403

    viewer_outcome = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/outcome",
        headers=auth_headers(viewer_token),
        json={"outcome": "rejected"},
    )
    assert viewer_outcome.status_code == 403

    report = await client.get(
        f"/api/v1/company/reports/{report_id}",
        headers=auth_headers(recruiter_token),
    )
    assert report.status_code == 200, report.text
    assert recruiter_email
    assert viewer_email


@pytest.mark.asyncio
async def test_activity_log_tracks_report_and_replay_views(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
):
    finish = await _complete_interview(client, candidate_token, role="frontend_engineer")
    candidate = await _candidate_profile(client, candidate_token)
    candidate_id = candidate["id"]
    interview_id = finish["interview_id"]
    report_id = finish["report_id"]

    report = await client.get(
        f"/api/v1/company/reports/{report_id}",
        headers=auth_headers(company_token),
    )
    assert report.status_code == 200, report.text

    replay = await client.get(
        f"/api/v1/company/interviews/{interview_id}/replay",
        headers=auth_headers(company_token),
    )
    assert replay.status_code == 200, replay.text

    activity = await client.get(
        f"/api/v1/company/candidates/{candidate_id}/activity",
        headers=auth_headers(company_token),
    )
    assert activity.status_code == 200, activity.text
    activity_types = [item["activity_type"] for item in activity.json()]
    assert "report_viewed" in activity_types
    assert "replay_viewed" in activity_types
