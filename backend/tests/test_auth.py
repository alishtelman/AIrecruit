"""Tests for auth endpoints: register, login, /me."""
import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import auth_headers, bearer_auth_headers


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
        "email": email, "password": "password123", "account_type": "candidate",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_requires_account_type(client: AsyncClient):
    email = f"login_contract_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "A",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_sets_http_only_cookie_and_me_accepts_cookie_session(client: AsyncClient):
    email = f"cookie_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Cookie User",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123", "account_type": "candidate",
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
        "email": email, "password": "password123", "account_type": "candidate",
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
        "email": email, "password": "password123", "account_type": "candidate",
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
        "email": email, "password": "password123", "account_type": "candidate",
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
            "email": email, "password": "password123", "account_type": "candidate",
        })
    assert login.status_code == 200
    bearer_token = login.json()["access_token"]

    change = await client.post(
        "/api/v1/auth/change-password",
        headers=bearer_auth_headers(bearer_token),
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
        "email": cookie_email, "password": "password123", "account_type": "candidate",
    })
    assert cookie_login.status_code == 200

    bearer_email = f"bearer_owner_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": bearer_email, "password": "password123", "full_name": "Bearer Owner",
    })

    async with AsyncClient(base_url=str(client.base_url)) as clean_client:
        bearer_login = await clean_client.post("/api/v1/auth/login", json={
            "email": bearer_email, "password": "password123", "account_type": "candidate",
        })
    assert bearer_login.status_code == 200
    bearer_token = bearer_login.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers=bearer_auth_headers(bearer_token))
    assert me.status_code == 200
    assert me.json()["email"] == bearer_email


@pytest.mark.asyncio
async def test_logout_clears_cookie_session(client: AsyncClient):
    email = f"logout_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email, "password": "password123", "full_name": "Logout User",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "password123", "account_type": "candidate",
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
        "email": email, "password": "wrongpass", "account_type": "candidate",
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


@pytest.mark.asyncio
async def test_platform_admin_bootstrap_login_and_me(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
        "account_type": "admin",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "platform_admin"


@pytest.mark.asyncio
async def test_candidate_login_rejects_company_and_admin_accounts(client: AsyncClient):
    company_email = f"company_wrong_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/company/register", json={
        "email": company_email,
        "password": "password123",
        "company_name": "Wrong Login Corp",
    })

    company_as_candidate = await client.post("/api/v1/auth/login", json={
        "email": company_email,
        "password": "password123",
        "account_type": "candidate",
    })
    assert company_as_candidate.status_code == 401
    assert company_as_candidate.json()["detail"] == "Account does not match this login type"

    await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
        "account_type": "admin",
    })
    admin_as_candidate = await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
        "account_type": "candidate",
    })
    assert admin_as_candidate.status_code == 401
    assert admin_as_candidate.json()["detail"] == "Account does not match this login type"


@pytest.mark.asyncio
async def test_company_login_rejects_candidate_and_admin_accounts(client: AsyncClient):
    candidate_email = f"candidate_wrong_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": candidate_email,
        "password": "password123",
        "full_name": "Wrong Login Candidate",
    })

    candidate_as_company = await client.post("/api/v1/auth/login", json={
        "email": candidate_email,
        "password": "password123",
        "account_type": "company",
    })
    assert candidate_as_company.status_code == 401
    assert candidate_as_company.json()["detail"] == "Account does not match this login type"

    await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
        "account_type": "admin",
    })
    admin_as_company = await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
        "account_type": "company",
    })
    assert admin_as_company.status_code == 401
    assert admin_as_company.json()["detail"] == "Account does not match this login type"


@pytest.mark.asyncio
async def test_admin_login_rejects_candidate_and_company_accounts(client: AsyncClient):
    candidate_email = f"candidate_admin_wrong_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": candidate_email,
        "password": "password123",
        "full_name": "Wrong Admin Candidate",
    })
    candidate_as_admin = await client.post("/api/v1/auth/login", json={
        "email": candidate_email,
        "password": "password123",
        "account_type": "admin",
    })
    assert candidate_as_admin.status_code == 401
    assert candidate_as_admin.json()["detail"] == "Account does not match this login type"

    company_email = f"company_admin_wrong_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/company/register", json={
        "email": company_email,
        "password": "password123",
        "company_name": "Wrong Admin Corp",
    })
    company_as_admin = await client.post("/api/v1/auth/login", json={
        "email": company_email,
        "password": "password123",
        "account_type": "admin",
    })
    assert company_as_admin.status_code == 401
    assert company_as_admin.json()["detail"] == "Account does not match this login type"


@pytest.mark.asyncio
async def test_role_protected_api_rejects_foreign_roles(client: AsyncClient):
    candidate_email = f"role_api_candidate_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": candidate_email,
        "password": "password123",
        "full_name": "Role API Candidate",
    })
    candidate_login = await client.post("/api/v1/auth/login", json={
        "email": candidate_email,
        "password": "password123",
        "account_type": "candidate",
    })
    assert candidate_login.status_code == 200, candidate_login.text
    candidate_token = candidate_login.json()["access_token"]

    company_from_candidate = await client.get(
        "/api/v1/company/candidates/page",
        headers=auth_headers(candidate_token),
    )
    assert company_from_candidate.status_code == 403

    company_email = f"role_api_company_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/company/register", json={
        "email": company_email,
        "password": "password123",
        "company_name": "Role API Corp",
    })
    company_login = await client.post("/api/v1/auth/login", json={
        "email": company_email,
        "password": "password123",
        "account_type": "company",
    })
    assert company_login.status_code == 200, company_login.text
    company_token = company_login.json()["access_token"]

    admin_from_company = await client.get("/api/v1/admin/users", headers=auth_headers(company_token))
    assert admin_from_company.status_code == 403

    admin_login = await client.post("/api/v1/auth/login", json={
        "email": settings.platform_admin_email,
        "password": settings.platform_admin_password,
        "account_type": "admin",
    })
    assert admin_login.status_code == 200, admin_login.text
    admin_token = admin_login.json()["access_token"]

    candidate_from_admin = await client.get("/api/v1/candidate/stats", headers=auth_headers(admin_token))
    assert candidate_from_admin.status_code == 403
