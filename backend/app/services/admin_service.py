from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.user import User
from app.schemas.admin import (
    AdminOverviewMetricsResponse,
    AdminOverviewResponse,
    AdminRecentCompanyResponse,
    AdminRecentInterviewResponse,
    AdminRecentReportResponse,
    AdminRecentUserResponse,
    AdminRuntimeStatusResponse,
)


async def get_admin_overview(db: AsyncSession) -> AdminOverviewResponse:
    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    active_candidates = await db.scalar(select(func.count()).select_from(Candidate)) or 0
    active_companies = await db.scalar(
        select(func.count()).select_from(Company).where(Company.is_active.is_(True))
    ) or 0
    company_members = await db.scalar(select(func.count()).select_from(CompanyMember)) or 0
    interviews_total = await db.scalar(select(func.count()).select_from(Interview)) or 0
    interviews_completed = await db.scalar(
        select(func.count()).select_from(Interview).where(
            Interview.status.in_(("completed", "report_generated"))
        )
    ) or 0
    reports_generated = await db.scalar(select(func.count()).select_from(AssessmentReport)) or 0

    recent_users_rows = (
        await db.execute(select(User).order_by(User.created_at.desc()).limit(8))
    ).scalars().all()

    owner_email_sq = (
        select(User.email)
        .where(User.id == Company.owner_user_id)
        .scalar_subquery()
    )
    recent_company_rows = (
        await db.execute(
            select(
                Company.id,
                Company.name,
                Company.is_active,
                Company.created_at,
                owner_email_sq.label("owner_email"),
            )
            .order_by(Company.created_at.desc())
            .limit(6)
        )
    ).all()

    report_exists_sq = (
        select(func.count())
        .select_from(AssessmentReport)
        .where(AssessmentReport.interview_id == Interview.id)
        .scalar_subquery()
    )
    recent_interview_rows = (
        await db.execute(
            select(
                Interview.id,
                Candidate.full_name,
                Interview.target_role,
                Interview.status,
                Interview.language,
                Interview.created_at,
                Interview.completed_at,
                report_exists_sq.label("report_count"),
            )
            .join(Candidate, Candidate.id == Interview.candidate_id)
            .order_by(Interview.created_at.desc())
            .limit(8)
        )
    ).all()

    recent_report_rows = (
        await db.execute(
            select(
                AssessmentReport.id,
                Candidate.full_name,
                Interview.target_role,
                AssessmentReport.overall_score,
                AssessmentReport.hiring_recommendation,
                AssessmentReport.created_at,
            )
            .join(Interview, Interview.id == AssessmentReport.interview_id)
            .join(Candidate, Candidate.id == AssessmentReport.candidate_id)
            .order_by(AssessmentReport.created_at.desc())
            .limit(8)
        )
    ).all()

    return AdminOverviewResponse(
        metrics=AdminOverviewMetricsResponse(
            total_users=total_users,
            active_candidates=active_candidates,
            active_companies=active_companies,
            company_members=company_members,
            interviews_total=interviews_total,
            interviews_completed=interviews_completed,
            reports_generated=reports_generated,
        ),
        runtime=AdminRuntimeStatusResponse(
            app_env=settings.APP_ENV,
            mock_ai_enabled=settings.allow_mock_ai,
            rate_limit_enabled=settings.rate_limit_enabled,
            platform_admin_bootstrap_enabled=settings.platform_admin_bootstrap_enabled,
        ),
        recent_users=[
            AdminRecentUserResponse(
                id=row.id,
                email=row.email,
                role=row.role,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in recent_users_rows
        ],
        recent_companies=[
            AdminRecentCompanyResponse(
                id=row.id,
                name=row.name,
                owner_email=row.owner_email,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in recent_company_rows
        ],
        recent_interviews=[
            AdminRecentInterviewResponse(
                id=row.id,
                candidate_name=row.full_name,
                target_role=row.target_role,
                status=row.status,
                language=row.language,
                created_at=row.created_at,
                completed_at=row.completed_at,
                report_ready=bool(row.report_count),
            )
            for row in recent_interview_rows
        ],
        recent_reports=[
            AdminRecentReportResponse(
                id=row.id,
                candidate_name=row.full_name,
                target_role=row.target_role,
                overall_score=row.overall_score,
                hiring_recommendation=row.hiring_recommendation,
                created_at=row.created_at,
            )
            for row in recent_report_rows
        ],
    )
