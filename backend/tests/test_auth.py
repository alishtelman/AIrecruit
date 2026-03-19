"""Tests for auth endpoints: register, login, /me."""
import uuid

import pytest
from httpx import AsyncClient

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
