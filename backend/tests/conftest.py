"""
Test fixtures.

Tests run against the live backend at http://localhost:8001.
Requires `docker compose up` to be running.

AI calls are handled by whatever interviewer is active (LLM or Mock).
Each test creates fresh users with unique emails to avoid conflicts.
"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

BASE_URL = "http://localhost:8001"


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(base_url=BASE_URL, timeout=60.0) as c:
        yield c


@pytest_asyncio.fixture
async def candidate_token(client: AsyncClient) -> str:
    """Register a fresh candidate and return their JWT token."""
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/candidate/register", json={
        "email": email,
        "password": "testpass123",
        "full_name": "Test Candidate",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def company_token(client: AsyncClient) -> str:
    """Register a fresh company admin and return their JWT token."""
    email = f"company_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/company/register", json={
        "email": email,
        "password": "testpass123",
        "company_name": "Test Corp",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
