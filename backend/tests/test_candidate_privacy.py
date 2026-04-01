"""Tests for candidate privacy controls and direct-share profiles."""
import io
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers

INTERVIEW_TEST_ANSWER = (
    "Я решил задачу по шагам и потому что это снижало риски, "
    "сначала проверял крайние случаи и только потом двигался дальше."
)


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
            json={"message": INTERVIEW_TEST_ANSWER},
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


@pytest.mark.asyncio
async def test_direct_link_visibility_hides_candidate_from_company_marketplace(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
):
    finish = await _complete_interview(client, candidate_token, role="backend_engineer")
    candidate = await _candidate_profile(client, candidate_token)
    candidate_id = candidate["id"]

    visible_before = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
    )
    assert visible_before.status_code == 200, visible_before.text
    assert any(item["candidate_id"] == candidate_id for item in visible_before.json())

    privacy = await client.patch(
        "/api/v1/candidate/privacy",
        headers=auth_headers(candidate_token),
        json={"visibility": "direct_link"},
    )
    assert privacy.status_code == 200, privacy.text
    share_token = privacy.json()["share_token"]
    assert share_token

    visible_after = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
    )
    assert visible_after.status_code == 200, visible_after.text
    assert all(item["candidate_id"] != candidate_id for item in visible_after.json())

    detail = await client.get(
        f"/api/v1/company/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert detail.status_code == 404, detail.text

    report = await client.get(
        f"/api/v1/company/reports/{finish['report_id']}",
        headers=auth_headers(company_token),
    )
    assert report.status_code == 404, report.text

    replay = await client.get(
        f"/api/v1/company/interviews/{finish['interview_id']}/replay",
        headers=auth_headers(company_token),
    )
    assert replay.status_code == 404, replay.text

    shared = await client.get(f"/api/v1/candidate/share/{share_token}")
    assert shared.status_code == 200, shared.text
    assert shared.json()["candidate_id"] == candidate_id
    assert len(shared.json()["reports"]) >= 1


@pytest.mark.asyncio
async def test_request_only_access_requires_candidate_approval_before_company_workspace_opens(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
):
    finish = await _complete_interview(client, candidate_token, role="qa_engineer")
    candidate = await _candidate_profile(client, candidate_token)
    candidate_id = candidate["id"]
    report_id = finish["report_id"]
    interview_id = finish["interview_id"]

    privacy = await client.patch(
        "/api/v1/candidate/privacy",
        headers=auth_headers(candidate_token),
        json={"visibility": "request_only"},
    )
    assert privacy.status_code == 200, privacy.text
    share_token = privacy.json()["share_token"]
    assert share_token

    shared_before = await client.get(f"/api/v1/candidate/share/{share_token}")
    assert shared_before.status_code == 200, shared_before.text
    assert shared_before.json()["requires_approval"] is True
    assert shared_before.json()["reports"] == []

    share_status_before = await client.get(
        f"/api/v1/company/share-links/{share_token}",
        headers=auth_headers(company_token),
    )
    assert share_status_before.status_code == 200, share_status_before.text
    assert share_status_before.json()["request_status"] is None
    assert share_status_before.json()["can_open_company_workspace"] is False

    detail_before = await client.get(
        f"/api/v1/company/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert detail_before.status_code == 404, detail_before.text

    request_access = await client.post(
        f"/api/v1/company/share-links/{share_token}/request-access",
        headers=auth_headers(company_token),
    )
    assert request_access.status_code == 200, request_access.text
    assert request_access.json()["request_status"] == "pending"

    requests = await client.get(
        "/api/v1/candidate/access-requests",
        headers=auth_headers(candidate_token),
    )
    assert requests.status_code == 200, requests.text
    request_item = requests.json()[0]
    assert request_item["company_name"] == "Test Corp"
    assert request_item["status"] == "pending"

    approve = await client.post(
        f"/api/v1/candidate/access-requests/{request_item['request_id']}/approve",
        headers=auth_headers(candidate_token),
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    share_status_after = await client.get(
        f"/api/v1/company/share-links/{share_token}",
        headers=auth_headers(company_token),
    )
    assert share_status_after.status_code == 200, share_status_after.text
    assert share_status_after.json()["request_status"] == "approved"
    assert share_status_after.json()["can_open_company_workspace"] is True

    detail_after = await client.get(
        f"/api/v1/company/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert detail_after.status_code == 200, detail_after.text

    shortlist = await client.post(
        "/api/v1/company/shortlists",
        headers=auth_headers(company_token),
        json={"name": f"Request Only {uuid.uuid4().hex[:6]}"},
    )
    assert shortlist.status_code == 201, shortlist.text
    shortlist_id = shortlist.json()["shortlist_id"]

    shortlist_add = await client.post(
        f"/api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert shortlist_add.status_code == 204, shortlist_add.text

    outcome = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/outcome",
        headers=auth_headers(company_token),
        json={"outcome": "interviewing", "notes": "Approved request flow"},
    )
    assert outcome.status_code == 200, outcome.text

    note = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/notes",
        headers=auth_headers(company_token),
        json={"body": "Candidate approved company access"},
    )
    assert note.status_code == 201, note.text

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


@pytest.mark.asyncio
async def test_private_and_request_only_profiles_are_excluded_from_public_benchmark_and_share(
    client: AsyncClient,
    candidate_token: str,
):
    role = "mobile_engineer"
    baseline_benchmark = await client.get(
        "/api/v1/candidate/salary/benchmark",
        params={"role": role},
    )
    assert baseline_benchmark.status_code == 200, baseline_benchmark.text
    baseline_total = sum(bucket["count"] for bucket in baseline_benchmark.json()["buckets"])

    second_email = f"privacy_benchmark_{uuid.uuid4().hex[:8]}@example.com"
    second_register = await client.post("/api/v1/auth/candidate/register", json={
        "email": second_email,
        "password": "testpass123",
        "full_name": "Privacy Benchmark Second",
    })
    assert second_register.status_code in {200, 201}, second_register.text
    second_login = await client.post("/api/v1/auth/login", json={
        "email": second_email,
        "password": "testpass123",
    })
    assert second_login.status_code == 200, second_login.text
    second_token = second_login.json()["access_token"]

    await _complete_interview(client, candidate_token, role=role)
    salary_first = await client.patch(
        "/api/v1/candidate/salary",
        headers=auth_headers(candidate_token),
        json={"salary_min": 70000, "salary_max": 85000, "currency": "USD"},
    )
    assert salary_first.status_code == 200, salary_first.text

    await _complete_interview(client, second_token, role=role)
    salary_second = await client.patch(
        "/api/v1/candidate/salary",
        headers=auth_headers(second_token),
        json={"salary_min": 120000, "salary_max": 140000, "currency": "USD"},
    )
    assert salary_second.status_code == 200, salary_second.text

    direct = await client.patch(
        "/api/v1/candidate/privacy",
        headers=auth_headers(second_token),
        json={"visibility": "direct_link"},
    )
    assert direct.status_code == 200, direct.text
    share_token = direct.json()["share_token"]
    assert share_token

    private_resp = await client.patch(
        "/api/v1/candidate/privacy",
        headers=auth_headers(second_token),
        json={"visibility": "private"},
    )
    assert private_resp.status_code == 200, private_resp.text
    assert private_resp.json()["share_token"] is None

    benchmark = await client.get(
        "/api/v1/candidate/salary/benchmark",
        params={"role": role},
    )
    assert benchmark.status_code == 200, benchmark.text
    total_count = sum(bucket["count"] for bucket in benchmark.json()["buckets"])
    assert total_count == baseline_total + 1

    shared_private = await client.get(f"/api/v1/candidate/share/{share_token}")
    assert shared_private.status_code == 404, shared_private.text

    request_only = await client.patch(
        "/api/v1/candidate/privacy",
        headers=auth_headers(candidate_token),
        json={"visibility": "request_only"},
    )
    assert request_only.status_code == 200, request_only.text
    assert request_only.json()["share_token"]

    benchmark_after_request_only = await client.get(
        "/api/v1/candidate/salary/benchmark",
        params={"role": role},
    )
    assert benchmark_after_request_only.status_code == 200, benchmark_after_request_only.text
    assert sum(bucket["count"] for bucket in benchmark_after_request_only.json()["buckets"]) == baseline_total
