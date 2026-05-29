import os
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.candidate import PROFILE_VISIBILITY_MARKETPLACE, Candidate
from app.models.company import Company
from app.models.company_assessment import CompanyAssessment
from app.models.company_member import CompanyMember
from app.models.hire_outcome import HireOutcome
from app.models.interview import Interview, InterviewMessage
from app.models.report import AssessmentReport
from app.models.resume import Resume
from app.models.skill import CandidateSkill
from app.models.shortlist import CompanyShortlist, CompanyShortlistCandidate
from app.models.template import InterviewTemplate
from app.models.user import User
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


async def _seed_test_company_and_candidate(
    db: AsyncSession, company_owner_id: uuid.UUID, candidate_user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a company and candidate for shortlist testing without needing LLM calls."""
    marker = uuid.uuid4().hex[:8]

    # 1. Fetch or update existing seeded entities
    company = Company(
        id=uuid.uuid4(),
        owner_user_id=company_owner_id,
        name=f"Direct Test Corp {marker}",
    )
    candidate = Candidate(
        id=uuid.uuid4(),
        user_id=candidate_user_id,
        full_name=f"Go Direct Candidate {marker}",
        profile_visibility=PROFILE_VISIBILITY_MARKETPLACE,
    )

    db.add(company)
    db.add(candidate)
    await db.flush()

    # 2. Add an interview and report
    interview = Interview(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        status="report_generated",
        target_role="backend_engineer",
        completed_at=datetime.utcnow() - timedelta(days=1),
    )
    db.add(interview)
    await db.flush()

    report = AssessmentReport(
        id=uuid.uuid4(),
        interview_id=interview.id,
        candidate_id=candidate.id,
        overall_score=8.5,
        hard_skills_score=8.0,
        soft_skills_score=8.5,
        communication_score=9.0,
        strengths=["Go skills", "Architecture design"],
        weaknesses=["None"],
        recommendations=["Hire"],
        hiring_recommendation="strong_yes",
        interview_summary="Excellent Go candidate",
        skill_tags=[{"skill": "Go", "proficiency": "expert", "mentions_count": 5}],
        red_flags=[],
        full_report_json={},
        model_version="test",
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    db.add(report)
    await db.commit()

    return company.id, candidate.id


@pytest.mark.asyncio
async def test_go_shortlist_crud_and_candidate_actions(
    client: AsyncClient,
    company_token: str,
    db_session: AsyncSession,
):
    # Decode token to get User ID
    # conftest handles token login and returns access token
    # Let's find the company admin user from database
    from jose import jwt
    from app.core.config import settings
    
    claims = jwt.decode(company_token, settings.SECRET_KEY, algorithms=["HS256"])
    company_owner_id = uuid.UUID(claims["sub"])

    # Create a fresh candidate user
    candidate_user_id = uuid.uuid4()
    candidate_user = User(
        id=candidate_user_id,
        email=f"candidate_direct_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="test",
        role="candidate",
    )
    db_session.add(candidate_user)
    await db_session.flush()

    company_id, candidate_id = await _seed_test_company_and_candidate(
        db_session, company_owner_id, candidate_user_id
    )

    # 1. POST /api/v1/company/shortlists (Create Shortlist)
    shortlist_name = f"Go Finalists {uuid.uuid4().hex[:6]}"
    create_resp = await client.post(
        "/api/v1/company/shortlists",
        headers=auth_headers(company_token),
        json={"name": shortlist_name},
    )
    assert create_resp.status_code == 201, create_resp.text
    shortlist = create_resp.json()
    assert shortlist["name"] == shortlist_name
    assert shortlist["candidate_count"] == 0
    shortlist_id = shortlist["shortlist_id"]

    # 2. GET /api/v1/company/shortlists (List Shortlists)
    list_resp = await client.get(
        "/api/v1/company/shortlists",
        headers=auth_headers(company_token),
    )
    assert list_resp.status_code == 200, list_resp.text
    shortlists = list_resp.json()
    assert len(shortlists) >= 1
    assert any(s["shortlist_id"] == shortlist_id for s in shortlists)

    # 3. POST /api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id} (Add Candidate)
    add_resp = await client.post(
        f"/api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert add_resp.status_code == 204, add_resp.text

    # 4. Search and verify Candidate shortlist membership in marketplace list
    search_resp = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
        params={"shortlist_id": shortlist_id},
    )
    assert search_resp.status_code == 200, search_resp.text
    results = search_resp.json()
    assert len(results) == 1
    assert results[0]["candidate_id"] == str(candidate_id)
    assert len(results[0]["shortlists"]) == 1
    assert results[0]["shortlists"][0]["shortlist_id"] == shortlist_id

    # 5. DELETE /api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id} (Remove Candidate)
    remove_resp = await client.delete(
        f"/api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert remove_resp.status_code == 204, remove_resp.text

    # Verify candidate removed from shortlist in search
    search_resp2 = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
        params={"shortlist_id": shortlist_id},
    )
    assert search_resp2.status_code == 200
    assert len(search_resp2.json()) == 0

    # 6. DELETE /api/v1/company/shortlists/{shortlist_id} (Delete Shortlist)
    delete_resp = await client.delete(
        f"/api/v1/company/shortlists/{shortlist_id}",
        headers=auth_headers(company_token),
    )
    assert delete_resp.status_code == 204, delete_resp.text

    # Verify shortlist deleted
    list_resp2 = await client.get(
        "/api/v1/company/shortlists",
        headers=auth_headers(company_token),
    )
    assert list_resp2.status_code == 200
    assert not any(s["shortlist_id"] == shortlist_id for s in list_resp2.json())
