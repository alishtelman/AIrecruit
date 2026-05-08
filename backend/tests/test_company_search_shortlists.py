"""Tests for company search, shortlists, and analytics foundation."""
import io
import os
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.candidate import PROFILE_VISIBILITY_MARKETPLACE, Candidate  # noqa: F401
from app.models.company import Company  # noqa: F401
from app.models.company_assessment import CompanyAssessment  # noqa: F401
from app.models.company_member import CompanyMember  # noqa: F401
from app.models.hire_outcome import HireOutcome  # noqa: F401
from app.models.interview import Interview, InterviewMessage  # noqa: F401
from app.models.report import AssessmentReport  # noqa: F401
from app.models.resume import Resume  # noqa: F401
from app.models.skill import CandidateSkill
from app.models.shortlist import CompanyShortlist, CompanyShortlistCandidate  # noqa: F401
from app.models.template import InterviewTemplate  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.company_service import list_verified_candidates
from tests.conftest import auth_headers

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://recruiting:recruiting@postgres:5432/recruiting",
)

INTERVIEW_TEST_ANSWER = (
    "Я решил задачу по шагам и потому что это снижало риски, "
    "сначала проверял крайние случаи и только потом двигался дальше."
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _upload_resume(client: AsyncClient, token: str) -> str:
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(token),
        files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["resume_id"]


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


async def _seed_marketplace_candidate_with_reports(
    db: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, str]:
    marker = uuid.uuid4().hex
    full_name = f"Latest Report Candidate {marker}"
    company_user = User(
        id=uuid.uuid4(),
        email=f"company_search_{marker}@example.com",
        hashed_password="unused",
        role="company_admin",
    )
    company = Company(
        id=uuid.uuid4(),
        owner_user_id=company_user.id,
        name=f"Search Parity {marker}",
    )
    candidate_user = User(
        id=uuid.uuid4(),
        email=f"candidate_search_{marker}@example.com",
        hashed_password="unused",
        role="candidate",
    )
    candidate = Candidate(
        id=uuid.uuid4(),
        user_id=candidate_user.id,
        full_name=full_name,
        profile_visibility=PROFILE_VISIBILITY_MARKETPLACE,
    )
    now = datetime.utcnow()
    old_interview = Interview(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        status="report_generated",
        target_role="backend_engineer",
        completed_at=now - timedelta(days=2),
    )
    new_interview = Interview(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        status="report_generated",
        target_role="devops_engineer",
        completed_at=now - timedelta(days=1),
    )
    old_report = AssessmentReport(
        id=uuid.uuid4(),
        interview_id=old_interview.id,
        candidate_id=candidate.id,
        overall_score=9.5,
        hard_skills_score=9.0,
        soft_skills_score=8.5,
        communication_score=8.0,
        strengths=[],
        weaknesses=[],
        recommendations=[],
        hiring_recommendation="strong_yes",
        interview_summary="Older strong Python report",
        skill_tags=[{"skill": "Python", "proficiency": "expert", "mentions_count": 4}],
        red_flags=[],
        full_report_json={},
        model_version="test",
        created_at=now - timedelta(days=2),
    )
    new_report = AssessmentReport(
        id=uuid.uuid4(),
        interview_id=new_interview.id,
        candidate_id=candidate.id,
        overall_score=4.0,
        hard_skills_score=4.0,
        soft_skills_score=5.0,
        communication_score=5.0,
        strengths=[],
        weaknesses=[],
        recommendations=[],
        hiring_recommendation="no",
        interview_summary="Latest lower Go report",
        skill_tags=[{"skill": "Go", "proficiency": "intermediate", "mentions_count": 2}],
        red_flags=[],
        full_report_json={},
        model_version="test",
        created_at=now - timedelta(days=1),
    )
    db.add_all([company_user, candidate_user])
    await db.flush()
    db.add_all([company, candidate])
    await db.flush()
    db.add_all([old_interview, new_interview])
    await db.flush()
    db.add_all([old_report, new_report])
    await db.flush()
    return company.id, candidate.id, old_report.id, new_report.id, full_name


@pytest.mark.asyncio
async def test_company_search_filters_by_skills_and_shortlist(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
    db_session: AsyncSession,
):
    finish = await _complete_interview(client, candidate_token)
    candidate = await _candidate_profile(client, candidate_token)
    candidate_id = uuid.UUID(candidate["id"])
    report_id = uuid.UUID(finish["report_id"])

    db_session.add_all(
        [
            CandidateSkill(
                candidate_id=candidate_id,
                report_id=report_id,
                skill_name="python",
                proficiency="expert",
                evidence_summary="Strong backend answer",
            ),
            CandidateSkill(
                candidate_id=candidate_id,
                report_id=report_id,
                skill_name="fastapi",
                proficiency="advanced",
                evidence_summary="Built REST APIs",
            ),
        ]
    )
    await db_session.commit()

    shortlist_resp = await client.post(
        "/api/v1/company/shortlists",
        headers=auth_headers(company_token),
        json={"name": f"Backend Finalists {uuid.uuid4().hex[:6]}"},
    )
    assert shortlist_resp.status_code == 201, shortlist_resp.text
    shortlist_id = shortlist_resp.json()["shortlist_id"]

    add_resp = await client.post(
        f"/api/v1/company/shortlists/{shortlist_id}/candidates/{candidate['id']}",
        headers=auth_headers(company_token),
    )
    assert add_resp.status_code == 204, add_resp.text

    filtered = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
        params=[
            ("skills", "python"),
            ("skills", "fastapi"),
            ("shortlist_id", shortlist_id),
        ],
    )
    assert filtered.status_code == 200, filtered.text
    items = filtered.json()
    assert len(items) == 1
    assert items[0]["candidate_id"] == candidate["id"]
    assert {tag["skill"].lower() for tag in items[0]["skill_tags"]} >= {"python", "fastapi"}
    assert {membership["shortlist_id"] for membership in items[0]["shortlists"]} == {shortlist_id}

    missing = await client.get(
        "/api/v1/company/candidates",
        headers=auth_headers(company_token),
        params=[("skills", "react"), ("shortlist_id", shortlist_id)],
    )
    assert missing.status_code == 200, missing.text
    assert missing.json() == []


@pytest.mark.asyncio
async def test_company_search_uses_latest_marketplace_report_for_sql_filters(
    db_session: AsyncSession,
):
    company_id, candidate_id, old_report_id, new_report_id, search_name = await _seed_marketplace_candidate_with_reports(
        db_session,
    )

    items = await list_verified_candidates(
        db_session,
        company_id=company_id,
        q=search_name,
    )

    target = next((item for item in items if item.candidate_id == candidate_id), None)
    assert target is not None
    assert target.report_id == new_report_id
    assert target.report_id != old_report_id
    assert target.target_role == "devops_engineer"
    assert target.overall_score == 4.0
    assert target.hiring_recommendation == "no"
    assert [tag["skill"] for tag in target.skill_tags or []] == ["Go"]

    old_score_filtered = await list_verified_candidates(
        db_session,
        company_id=company_id,
        q=search_name,
        min_score=9,
    )
    assert all(item.candidate_id != candidate_id for item in old_score_filtered)

    old_recommendation_filtered = await list_verified_candidates(
        db_session,
        company_id=company_id,
        q=search_name,
        recommendation="strong_yes",
    )
    assert all(item.candidate_id != candidate_id for item in old_recommendation_filtered)

    old_role_filtered = await list_verified_candidates(
        db_session,
        company_id=company_id,
        q=search_name,
        role="backend_engineer",
    )
    assert all(item.candidate_id != candidate_id for item in old_role_filtered)

    old_skill_filtered = await list_verified_candidates(
        db_session,
        company_id=company_id,
        q=search_name,
        skills=["python"],
    )
    assert all(item.candidate_id != candidate_id for item in old_skill_filtered)

    latest_skill_filtered = await list_verified_candidates(
        db_session,
        company_id=company_id,
        q=search_name,
        skills=["go"],
    )
    assert [item.candidate_id for item in latest_skill_filtered] == [candidate_id]


@pytest.mark.asyncio
async def test_company_analytics_include_shortlists_funnel_and_salary(
    client: AsyncClient,
    company_token: str,
    candidate_token: str,
):
    finish = await _complete_interview(client, candidate_token, role="frontend_engineer")
    candidate = await _candidate_profile(client, candidate_token)
    candidate_id = candidate["id"]

    salary_resp = await client.patch(
        "/api/v1/candidate/salary",
        headers=auth_headers(candidate_token),
        json={"salary_min": 70000, "salary_max": 90000, "currency": "USD"},
    )
    assert salary_resp.status_code == 200, salary_resp.text

    shortlist_resp = await client.post(
        "/api/v1/company/shortlists",
        headers=auth_headers(company_token),
        json={"name": f"Frontend Pipeline {uuid.uuid4().hex[:6]}"},
    )
    assert shortlist_resp.status_code == 201, shortlist_resp.text
    shortlist_id = shortlist_resp.json()["shortlist_id"]

    add_resp = await client.post(
        f"/api/v1/company/shortlists/{shortlist_id}/candidates/{candidate_id}",
        headers=auth_headers(company_token),
    )
    assert add_resp.status_code == 204, add_resp.text

    outcome_resp = await client.post(
        f"/api/v1/company/candidates/{candidate_id}/outcome",
        headers=auth_headers(company_token),
        json={"outcome": "hired", "notes": "Strong fit"},
    )
    assert outcome_resp.status_code == 200, outcome_resp.text

    overview = await client.get(
        "/api/v1/company/analytics/overview",
        headers=auth_headers(company_token),
    )
    assert overview.status_code == 200, overview.text
    overview_data = overview.json()
    assert overview_data["total_candidates"] >= 1
    assert overview_data["shortlisted_candidates"] >= 1
    assert len(overview_data["recommendation_breakdown"]) >= 1

    funnel = await client.get(
        "/api/v1/company/analytics/funnel",
        headers=auth_headers(company_token),
    )
    assert funnel.status_code == 200, funnel.text
    funnel_rows = funnel.json()["rows"]
    assert any(row["hired"] >= 1 for row in funnel_rows)

    salary = await client.get(
        "/api/v1/company/analytics/salary",
        headers=auth_headers(company_token),
        params={"shortlist_id": shortlist_id},
    )
    assert salary.status_code == 200, salary.text
    salary_data = salary.json()
    assert salary_data["shortlist_id"] == shortlist_id
    assert any(role["candidate_count"] >= 1 for role in salary_data["roles"])
    assert finish["report_id"]
