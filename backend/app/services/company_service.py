import uuid

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.user import User
from app.schemas.company import (
    CandidateDetailResponse,
    CandidateListItemResponse,
    ReportWithRoleResponse,
)


async def list_verified_candidates(db: AsyncSession) -> list[CandidateListItemResponse]:
    """Return one entry per candidate — their most recent completed report."""
    result = await db.execute(
        select(AssessmentReport, Interview, Candidate, User)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .join(Candidate, AssessmentReport.candidate_id == Candidate.id)
        .join(User, Candidate.user_id == User.id)
        .order_by(desc(AssessmentReport.created_at))
    )
    rows = result.all()

    seen: set[uuid.UUID] = set()
    items: list[CandidateListItemResponse] = []
    for report, interview, candidate, user in rows:
        if candidate.id not in seen:
            seen.add(candidate.id)
            items.append(
                CandidateListItemResponse(
                    candidate_id=candidate.id,
                    full_name=candidate.full_name,
                    email=user.email,
                    target_role=interview.target_role,
                    overall_score=report.overall_score,
                    hiring_recommendation=report.hiring_recommendation,
                    interview_summary=report.interview_summary,
                    report_id=report.id,
                    completed_at=interview.completed_at,
                )
            )
    return items


async def get_candidate_detail(
    db: AsyncSession,
    candidate_id: uuid.UUID,
) -> CandidateDetailResponse | None:
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        return None

    user = await db.scalar(select(User).where(User.id == candidate.user_id))
    if not user:
        return None

    result = await db.execute(
        select(AssessmentReport, Interview)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .where(AssessmentReport.candidate_id == candidate_id)
        .order_by(desc(AssessmentReport.created_at))
    )
    rows = result.all()

    reports = [
        ReportWithRoleResponse(
            report_id=report.id,
            target_role=interview.target_role,
            overall_score=report.overall_score,
            hard_skills_score=report.hard_skills_score,
            soft_skills_score=report.soft_skills_score,
            communication_score=report.communication_score,
            problem_solving_score=report.problem_solving_score,
            strengths=report.strengths,
            weaknesses=report.weaknesses,
            recommendations=report.recommendations,
            hiring_recommendation=report.hiring_recommendation,
            interview_summary=report.interview_summary,
            created_at=report.created_at,
            competency_scores=report.competency_scores,
            skill_tags=report.skill_tags,
            red_flags=report.red_flags,
            response_consistency=report.response_consistency,
        )
        for report, interview in rows
    ]

    return CandidateDetailResponse(
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        email=user.email,
        reports=reports,
    )
