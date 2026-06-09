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


async def _complete_minimum_interview(
    client: AsyncClient,
    token: str,
    interview_id: str,
) -> None:
    answers = [
        "Готов начать интервью.",
        "Я проектировал backend API, декомпозировал задачу, оценивал риски и выпускал изменения в production.",
        "В одном проекте я оптимизировал PostgreSQL-запросы через EXPLAIN ANALYZE, индексы и контроль p95 latency.",
        "Для Redis-кеширования я задавал TTL, инвалидацию, fallback и мониторинг hit rate после релиза.",
        "При инциденте я смотрел логи, метрики, последний релиз, формировал гипотезы и согласовывал rollback.",
        "Я объяснял бизнесу impact, сроки восстановления, workaround и следующий контрольный шаг простым языком.",
        "По безопасности я проверял права доступа, секреты, input validation и аудит критичных операций.",
        "После релиза я сверял error rate, latency, throughput и пользовательский impact с целевыми метриками.",
        "В финале я фиксировал выводы в postmortem, назначал action items и проверял, что повторяемость снизилась.",
    ]

    for answer in answers:
        msg = await client.post(
            f"/api/v1/interviews/{interview_id}/message",
            headers=auth_headers(token),
            json={"message": answer},
        )
        assert msg.status_code == 200, msg.text


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
    assert "daily_trends" in data
    assert len(data["daily_trends"]) == 7
    assert "interviews_in_progress" in data["metrics"]
    assert "completion_rate_pct" in data["metrics"]
    assert "reports_generated_7d" in data["metrics"]
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
async def test_admin_can_update_platform_ai_runtime_without_prompt_body_in_audit(client: AsyncClient):
    token = await _admin_token(client)
    secret_prompt = "do not store this full prompt body in audit metadata"
    resp = await client.put(
        "/api/v1/admin/ai-settings",
        headers=auth_headers(token),
        json={
            "llm_provider": "openai",
            "interviewer_model": "gpt-5.4-mini",
            "assessor_model": "gpt-5.4-mini",
            "llm_timeout_seconds": 12,
            "llm_max_retries": 2,
            "interviewer_prompt_override": secret_prompt,
            "assessor_prompt_override": "assessor prompt body",
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["llm_provider"] == "openai"
    assert payload["interviewer_model"] == "gpt-5.4-mini"
    assert payload["assessor_model"] == "gpt-5.4-mini"
    assert payload["llm_timeout_seconds"] == 12
    assert payload["llm_max_retries"] == 2
    assert payload["llm_required_api_key"] == "OPENAI_API_KEY"
    assert payload["llm_model_options"] == {
        "openai": ["gpt-5.4-mini", "gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini"],
    }

    diagnostics = await client.get("/api/v1/admin/ai-settings/diagnostics", headers=auth_headers(token))
    assert diagnostics.status_code == 200, diagnostics.text
    diagnostics_payload = diagnostics.json()
    assert diagnostics_payload["provider"] == "openai"
    assert diagnostics_payload["interviewer_model"] == "gpt-5.4-mini"
    assert diagnostics_payload["required_api_key"] == "OPENAI_API_KEY"
    assert "last_success" in diagnostics_payload

    audit = await client.get("/api/v1/admin/audit-log", headers=auth_headers(token))
    assert audit.status_code == 200, audit.text
    encoded = audit.text
    assert "platform_ai_settings_updated" in encoded
    assert secret_prompt not in encoded

    await _set_platform_settings(
        llm_provider="openai",
        interviewer_model="gpt-5.4-mini",
        assessor_model="gpt-5.4-mini",
        interviewer_prompt_override=None,
        assessor_prompt_override=None,
        llm_timeout_seconds=30,
        llm_max_retries=1,
    )


@pytest.mark.asyncio
async def test_admin_rejects_invalid_provider_model_pair(client: AsyncClient):
    token = await _admin_token(client)
    resp = await client.put(
        "/api/v1/admin/ai-settings",
        headers=auth_headers(token),
        json={
            "llm_provider": "legacy-provider",
            "interviewer_model": "gemini-2.5-flash",
            "assessor_model": "gemini-2.5-flash",
        },
    )
    assert resp.status_code == 422, resp.text


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

    await _complete_minimum_interview(client, candidate_token, interview_id)

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
async def test_admin_cannot_deactivate_self(client: AsyncClient):
    token = await _admin_token(client)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text

    updated = await client.put(
        f"/api/v1/admin/users/{me.json()['id']}/status",
        headers=auth_headers(token),
        json={"is_active": False},
    )

    assert updated.status_code == 409, updated.text
    assert "cannot deactivate" in updated.json()["detail"].lower()


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
    assert "assessments_total" in company
    assert "assessments_in_progress" in company
    assert "reports_generated" in company
    assert "last_activity_at" in company

    filtered_by_owner = await client.get(
        "/api/v1/admin/companies",
        headers=auth_headers(token),
        params={"q": company_email, "status": "active"},
    )
    assert filtered_by_owner.status_code == 200, filtered_by_owner.text
    assert any(item["owner_email"] == company_email for item in filtered_by_owner.json()["items"])

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

    await _complete_minimum_interview(client, candidate_token, interview_id)

    finish = await client.post(
        f"/api/v1/interviews/{interview_id}/finish",
        headers=auth_headers(candidate_token),
    )
    assert finish.status_code == 200, finish.text

    reports = await client.get("/api/v1/admin/reports", headers=auth_headers(token))
    assert reports.status_code == 200, reports.text
    assert len(reports.json()["items"]) >= 1
    report_id = reports.json()["items"][0]["id"]

    report_detail = await client.get(f"/api/v1/admin/reports/{report_id}", headers=auth_headers(token))
    assert report_detail.status_code == 200, report_detail.text
    assert report_detail.json()["id"] == report_id

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

    filtered = await client.get(
        "/api/v1/admin/audit-log",
        headers=auth_headers(token),
        params={
            "q": "global platform",
            "action": "platform_settings_updated",
            "entity_type": "platform_settings",
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()["items"]) >= 1
    assert all(item["action"] == "platform_settings_updated" for item in filtered.json()["items"])
    assert all(item["entity_type"] == "platform_settings" for item in filtered.json()["items"])
