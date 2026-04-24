import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import auth_headers


async def _admin_token(client: AsyncClient) -> str:
    login = await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
    })
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _set_platform_settings(**values) -> None:
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            assignments = ", ".join(f"{key} = :{key}" for key in values.keys())
            await session.execute(
                text(f"UPDATE platform_settings SET {assignments} WHERE id = 1"),
                values,
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _upload_resume(client: AsyncClient, token: str) -> None:
    import io

    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(token),
        files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_admin_overview_requires_platform_admin(client: AsyncClient, candidate_token: str):
    resp = await client.get("/api/v1/admin/overview", headers=auth_headers(candidate_token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_overview_returns_metrics_for_platform_admin(client: AsyncClient):
    token = await _admin_token(client)

    resp = await client.get("/api/v1/admin/overview", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "metrics" in data
    assert "runtime" in data
    assert "recent_users" in data


@pytest.mark.asyncio
async def test_admin_can_update_platform_settings(client: AsyncClient):
    token = await _admin_token(client)
    resp = await client.put(
        "/api/v1/admin/platform-settings",
        headers=auth_headers(token),
        json={"candidate_registration_enabled": False, "employee_invites_enabled": False},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["candidate_registration_enabled"] is False
    assert payload["employee_invites_enabled"] is False

    await _set_platform_settings(
        candidate_registration_enabled=True,
        employee_invites_enabled=True,
    )


@pytest.mark.asyncio
async def test_candidate_registration_respects_platform_toggle(client: AsyncClient):
    await _set_platform_settings(candidate_registration_enabled=False)
    try:
        resp = await client.post("/api/v1/auth/candidate/register", json={
            "email": "blocked_candidate@example.com",
            "password": "password123",
            "full_name": "Blocked Candidate",
        })
        assert resp.status_code == 403, resp.text
    finally:
        await _set_platform_settings(candidate_registration_enabled=True)


@pytest.mark.asyncio
async def test_company_registration_respects_platform_toggle(client: AsyncClient):
    await _set_platform_settings(company_registration_enabled=False)
    try:
        resp = await client.post("/api/v1/auth/company/register", json={
            "email": "blocked_company@example.com",
            "password": "password123",
            "company_name": "Blocked Company",
        })
        assert resp.status_code == 403, resp.text
    finally:
        await _set_platform_settings(company_registration_enabled=True)


@pytest.mark.asyncio
async def test_employee_invite_respects_platform_toggle(client: AsyncClient, company_token: str):
    await _set_platform_settings(employee_invites_enabled=False)
    try:
        resp = await client.post(
            "/api/v1/company/members/invite",
            headers=auth_headers(company_token),
            json={"email": "member_blocked@example.com", "role": "viewer"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _set_platform_settings(employee_invites_enabled=True)


@pytest.mark.asyncio
async def test_admin_can_list_and_requeue_interviews(client: AsyncClient, candidate_token: str):
    token = await _admin_token(client)
    await _upload_resume(client, candidate_token)

    start = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start.status_code == 201, start.text
    interview_id = start.json()["interview_id"]

    while True:
        msg = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": "Я проектировал API, работал с PostgreSQL и Redis в production."},
        )
        assert msg.status_code == 200, msg.text
        if msg.json()["current_question"] is None:
            break

    finish = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish.status_code == 200, finish.text

    listed = await client.get("/api/v1/admin/interviews", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    target = next((item for item in items if item["id"] == interview_id), None)
    assert target is not None

    requeue = await client.post(
        f"/api/v1/admin/interviews/{interview_id}/requeue-report",
        headers=auth_headers(token),
    )
    assert requeue.status_code == 200, requeue.text
    assert requeue.json()["processing_state"] == "processing"


@pytest.mark.asyncio
async def test_admin_can_list_and_toggle_users(client: AsyncClient, candidate_token: str):
    token = await _admin_token(client)

    listed = await client.get("/api/v1/admin/users", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    me = next((item for item in items if item["role"] == "candidate"), None)
    assert me is not None

    updated = await client.put(
        f"/api/v1/admin/users/{me['id']}/status",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False

    me_resp = await client.get("/api/v1/auth/me", headers=auth_headers(candidate_token))
    assert me_resp.status_code == 401

    restore = await client.put(
        f"/api/v1/admin/users/{me['id']}/status",
        headers=auth_headers(token),
        json={"is_active": True},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["is_active"] is True


@pytest.mark.asyncio
async def test_admin_can_list_and_toggle_companies_and_access_is_blocked(client: AsyncClient, company_token: str):
    token = await _admin_token(client)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(company_token))
    assert me.status_code == 200, me.text
    company_email = me.json()["email"]

    listed = await client.get("/api/v1/admin/companies", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    company = next((item for item in items if item["owner_email"] == company_email), None)
    assert company is not None

    updated = await client.put(
        f"/api/v1/admin/companies/{company['id']}/status",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False

    blocked = await client.get("/api/v1/company/members", headers=auth_headers(company_token))
    assert blocked.status_code == 403, blocked.text

    restore = await client.put(
        f"/api/v1/admin/companies/{company['id']}/status",
        headers=auth_headers(token),
        json={"is_active": True},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["is_active"] is True


@pytest.mark.asyncio
async def test_admin_can_list_reports_and_audit_log(client: AsyncClient, candidate_token: str):
    token = await _admin_token(client)
    await _upload_resume(client, candidate_token)

    start = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer"},
    )
    assert start.status_code == 201, start.text
    interview_id = start.json()["interview_id"]

    while True:
        msg = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(candidate_token),
            json={"message": "Я строил production API, оптимизировал PostgreSQL и настраивал Redis кеширование."},
        )
        assert msg.status_code == 200, msg.text
        if msg.json()["current_question"] is None:
            break

    finish = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish.status_code == 200, finish.text

    reports = await client.get("/api/v1/admin/reports", headers=auth_headers(token))
    assert reports.status_code == 200, reports.text
    assert len(reports.json()["items"]) >= 1

    updated = await client.put(
        "/api/v1/admin/platform-settings",
        headers=auth_headers(token),
        json={"maintenance_mode_enabled": True},
    )
    assert updated.status_code == 200, updated.text

    await _set_platform_settings(maintenance_mode_enabled=False)

    audit = await client.get("/api/v1/admin/audit-log", headers=auth_headers(token))
    assert audit.status_code == 200, audit.text
    summaries = [item["summary"] for item in audit.json()["items"]]
    assert any("Updated global platform settings" in summary for summary in summaries)
