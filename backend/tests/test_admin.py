import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_admin_overview_requires_platform_admin(client: AsyncClient, candidate_token: str):
    resp = await client.get("/api/v1/admin/overview", headers=auth_headers(candidate_token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_overview_returns_metrics_for_platform_admin(client: AsyncClient):
    login = await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
    })
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/admin/overview", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "metrics" in data
    assert "runtime" in data
    assert "recent_users" in data
