"""Tests for auth endpoints: register, login, /me."""
import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_candidate_register(client: AsyncClient):
    email = f"cand_{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post("/api/v1/auth/candidate/register", json={
        "email": email,
        "password": "password123",
        "full_name": "John Doe",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["user"]["email"] == email
    assert data["user"]["role"] == "candidate"
    assert data["candidate"]["full_name"] == "John Doe"


@pytest.mark.asyncio
async def test_candidate_register_duplicate(client: AsyncClient):
    email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "A",
    })
    resp = await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "B",
    })
    assert resp.status_code in (400, 409)


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    email = f"login_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "A",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_sets_http_only_cookie_and_me_accepts_cookie_session(client: AsyncClient):
    email = f"cookie_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Cookie User",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "airecruit_session=" in set_cookie
    assert "HttpOnly" in set_cookie

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


@pytest.mark.asyncio
async def test_cookie_auth_takes_precedence_over_invalid_bearer(client: AsyncClient):
    email = f"cookie_priority_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Cookie Priority User",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert login.status_code == 200

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == email


@pytest.mark.asyncio
async def test_cookie_write_rejects_missing_csrf_origin(client: AsyncClient):
    email = f"cookie_csrf_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Cookie CSRF User",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert login.status_code == 200

    change = await client.post("/api/v1/auth/change-password", json={
        "current_password": "password123",
        "new_password": "password124",
    })
    assert change.status_code == 403
    assert change.json()["detail"] == "CSRF validation failed"


@pytest.mark.asyncio
async def test_cookie_write_allows_trusted_csrf_origin(client: AsyncClient):
    email = f"cookie_csrf_ok_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Cookie CSRF Allowed",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert login.status_code == 200

    change = await client.post(
        "/api/v1/auth/change-password",
        headers={"Origin": "http://localhost:3000"},
        json={
            "current_password": "password123",
            "new_password": "password124",
        },
    )
    assert change.status_code == 204, change.text


@pytest.mark.asyncio
async def test_bearer_write_does_not_require_csrf_origin(client: AsyncClient):
    email = f"bearer_csrf_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Bearer CSRF User",
    })

    async with AsyncClient(base_url=str(client.base_url)) as clean_client:
        login = await clean_client.post("/api/v1/auth/login", json={
            "email": email, "password": "password123",
        })
    assert login.status_code == 200
    bearer_token = login.json()["access_token"]

    change = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(bearer_token),
        json={
            "current_password": "password123",
            "new_password": "password124",
        },
    )
    assert change.status_code == 204, change.text


def test_bearer_auth_flag_controls_runtime_behavior():
    original_allow_bearer = settings.AUTH_ALLOW_BEARER
    try:
        settings.AUTH_ALLOW_BEARER = True
        assert settings.allow_bearer_auth is True
        settings.AUTH_ALLOW_BEARER = False
        assert settings.allow_bearer_auth is False
    finally:
        settings.AUTH_ALLOW_BEARER = original_allow_bearer


@pytest.mark.asyncio
async def test_valid_bearer_overrides_cookie_session(client: AsyncClient):
    cookie_email = f"cookie_owner_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": cookie_email, "password": "password123", "full_name": "Cookie Owner",
    })
    cookie_login = await client.post("/api/v1/auth/login", json={
        "email": cookie_email, "password": "password123",
    })
    assert cookie_login.status_code == 200

    bearer_email = f"bearer_owner_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": bearer_email, "password": "password123", "full_name": "Bearer Owner",
    })

    async with AsyncClient(base_url=str(client.base_url)) as clean_client:
        bearer_login = await clean_client.post("/api/v1/auth/login", json={
            "email": bearer_email, "password": "password123",
        })
    assert bearer_login.status_code == 200
    bearer_token = bearer_login.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers=auth_headers(bearer_token))
    assert me.status_code == 200
    assert me.json()["email"] == bearer_email


@pytest.mark.asyncio
async def test_logout_clears_cookie_session(client: AsyncClient):
    email = f"logout_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Logout User",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert login.status_code == 200

    me_before = await client.get("/api/v1/auth/me")
    assert me_before.status_code == 200

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    me_after = await client.get("/api/v1/auth/me")
    assert me_after.status_code in (401, 403)


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    email = f"wrong_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "A",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "wrongpass",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient, candidate_token: str):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(candidate_token))
    assert resp.status_code == 200
    assert resp.json()["role"] == "candidate"


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_company_register(client: AsyncClient):
    email = f"comp_{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post("/api/v1/auth/company/register", json={
        "email": email,
        "password": "password123",
        "company_name": "Acme Inc",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["company_name"] == "Acme Inc"
    assert data["email"] == email
