import os
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from jose import jwt

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.user import User
from app.models.resume import Resume
from tests.conftest import auth_headers

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://recruiting:recruiting@postgres:5432/recruiting",
)

@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_go_candidate_profile_and_access_actions(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
    db_session: AsyncSession,
):
    # 1. Decode tokens
    comp_claims = jwt.decode(company_token, settings.SECRET_KEY, algorithms=["HS256"])
    company_owner_id = uuid.UUID(comp_claims["sub"])

    cand_claims = jwt.decode(candidate_token, settings.SECRET_KEY, algorithms=["HS256"])
    candidate_user_id = uuid.UUID(cand_claims["sub"])

    # Wait for the candidate and company to be populated from auth registration
    # Let's verify we can retrieve them
    candidate = None
    import asyncio
    for _ in range(5):
        from sqlalchemy import select
        res = await db_session.execute(select(Candidate).where(Candidate.user_id == candidate_user_id))
        candidate = res.scalar_one_or_none()
        if candidate:
            break
        await asyncio.sleep(0.2)
    assert candidate is not None

    company = None
    for _ in range(5):
        from sqlalchemy import select
        res = await db_session.execute(select(Company).where(Company.owner_user_id == company_owner_id))
        company = res.scalar_one_or_none()
        if company:
            break
        await asyncio.sleep(0.2)
    assert company is not None

    # 2. Test Salary Update
    salary_resp = await client.patch(
        "/api/v1/candidate/salary",
        headers=auth_headers(candidate_token),
        json={"salary_min": 100000, "salary_max": 120000, "currency": "EUR"},
    )
    assert salary_resp.status_code == 200, salary_resp.text
    assert salary_resp.json()["salary_currency"] == "EUR"

    salary_get = await client.get("/api/v1/candidate/salary", headers=auth_headers(candidate_token))
    assert salary_get.status_code == 200
    assert salary_get.json()["salary_min"] == 100000

    # 3. Test Privacy Update
    priv_resp = await client.patch(
        "/api/v1/candidate/privacy",
        headers=auth_headers(candidate_token),
        json={"visibility": "request_only"},
    )
    assert priv_resp.status_code == 200, priv_resp.text
    assert priv_resp.json()["visibility"] == "request_only"
    share_token = priv_resp.json()["share_token"]
    assert share_token is not None

    priv_get = await client.get("/api/v1/candidate/privacy", headers=auth_headers(candidate_token))
    assert priv_get.status_code == 200
    assert priv_get.json()["visibility"] == "request_only"

    # 4. Test Public Share Link
    share_get = await client.get(f"/api/v1/candidate/share/{share_token}")
    assert share_get.status_code == 200
    assert share_get.json()["visibility"] == "request_only"

    # 5. Company checks share link
    co_share_get = await client.get(
        f"/api/v1/company/share-links/{share_token}",
        headers=auth_headers(company_token)
    )
    assert co_share_get.status_code == 200
    assert co_share_get.json()["can_open_company_workspace"] is False

    # 6. Company requests access
    req_access = await client.post(
        f"/api/v1/company/share-links/{share_token}/request-access",
        headers=auth_headers(company_token)
    )
    assert req_access.status_code == 200

    # 7. Candidate views access requests
    cand_reqs = await client.get("/api/v1/candidate/access-requests", headers=auth_headers(candidate_token))
    assert cand_reqs.status_code == 200
    req_list = cand_reqs.json()
    assert len(req_list) == 1
    request_id = req_list[0]["request_id"]
    assert req_list[0]["status"] == "pending"

    # 8. Candidate approves access
    appr_resp = await client.post(
        f"/api/v1/candidate/access-requests/{request_id}/approve",
        headers=auth_headers(candidate_token)
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "approved"

    # 9. Company checks share link again
    co_share_get_2 = await client.get(
        f"/api/v1/company/share-links/{share_token}",
        headers=auth_headers(company_token)
    )
    assert co_share_get_2.status_code == 200
    assert co_share_get_2.json()["can_open_company_workspace"] is True
