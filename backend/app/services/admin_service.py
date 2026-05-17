import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit_log import AdminAuditLog
from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.user import User
from app.schemas.admin import (
    AdminAuditLogItemResponse,
    AdminAuditLogListResponse,
    AdminCompanyListItemResponse,
    AdminCompanyListResponse,
    AdminInterviewListItemResponse,
    AdminInterviewListResponse,
    AdminOverviewMetricsResponse,
    AdminOverviewResponse,
    AdminReportListItemResponse,
    AdminReportListResponse,
    AdminRecentCompanyResponse,
    AdminRecentInterviewResponse,
    AdminRecentReportResponse,
    AdminRecentUserResponse,
    AdminRuntimeStatusResponse,
    AdminUserListItemResponse,
    AdminUserListResponse,
)
from app.services.interview_service import _read_report_diagnostics, _schedule_report_generation
from app.services.platform_settings_service import get_platform_settings_payload, update_platform_settings


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


async def get_admin_platform_settings(db: AsyncSession) -> dict:
    return await get_platform_settings_payload(db)


async def update_admin_platform_settings(
    db: AsyncSession,
    *,
    candidate_registration_enabled: bool | None = None,
    company_registration_enabled: bool | None = None,
    employee_invites_enabled: bool | None = None,
    maintenance_mode_enabled: bool | None = None,
    proctoring_policy_mode: str | None = None,
    interviewer_model_preference: str | None = None,
    assessor_model_preference: str | None = None,
    llm_provider: str | None = None,
    interviewer_model: str | None = None,
    assessor_model: str | None = None,
    interviewer_prompt_override: str | None = None,
    assessor_prompt_override: str | None = None,
    llm_timeout_seconds: int | None = None,
    llm_max_retries: int | None = None,
) -> dict:
    payload = await update_platform_settings(
        db,
        candidate_registration_enabled=candidate_registration_enabled,
        company_registration_enabled=company_registration_enabled,
        employee_invites_enabled=employee_invites_enabled,
        maintenance_mode_enabled=maintenance_mode_enabled,
        proctoring_policy_mode=proctoring_policy_mode,
        interviewer_model_preference=interviewer_model_preference,
        assessor_model_preference=assessor_model_preference,
        llm_provider=llm_provider,
        interviewer_model=interviewer_model,
        assessor_model=assessor_model,
        interviewer_prompt_override=interviewer_prompt_override,
        assessor_prompt_override=assessor_prompt_override,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_max_retries=llm_max_retries,
    )
    return payload


async def list_admin_interviews(
    db: AsyncSession,
    *,
    q: str | None = None,
    status: str | None = None,
    limit: int = 40,
) -> AdminInterviewListResponse:
    stmt = (
        select(
            Interview,
            Candidate.full_name,
            User.email,
            AssessmentReport.id.label("report_id"),
            AssessmentReport.overall_score,
            AssessmentReport.hiring_recommendation,
        )
        .join(Candidate, Candidate.id == Interview.candidate_id)
        .join(User, User.id == Candidate.user_id)
        .outerjoin(AssessmentReport, AssessmentReport.interview_id == Interview.id)
        .order_by(desc(Interview.created_at))
        .limit(min(max(limit, 1), 100))
    )

    if status:
        stmt = stmt.where(Interview.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((Candidate.full_name.ilike(like)) | (User.email.ilike(like)))

    rows = (await db.execute(stmt)).all()
    items: list[AdminInterviewListItemResponse] = []
    for interview, candidate_name, candidate_email, report_id, overall_score, hiring_recommendation in rows:
        diagnostics = _read_report_diagnostics(interview)
        if report_id:
            processing_state = "ready"
        elif interview.status == "failed":
            processing_state = "failed"
        elif interview.status in {"completed", "report_processing"}:
            processing_state = "processing"
        else:
            processing_state = "pending"
        if diagnostics and diagnostics.get("last_status") == "failed" and not report_id:
            processing_state = "failed"

        items.append(
            AdminInterviewListItemResponse(
                id=interview.id,
                candidate_name=candidate_name,
                candidate_email=candidate_email,
                target_role=interview.target_role,
                status=interview.status,
                language=interview.language,
                created_at=interview.created_at,
                completed_at=interview.completed_at,
                report_id=report_id,
                overall_score=overall_score,
                hiring_recommendation=hiring_recommendation,
                processing_state=processing_state,
            )
        )

    return AdminInterviewListResponse(items=items)


async def admin_requeue_interview_report(
    db: AsyncSession,
    interview_id: uuid.UUID,
) -> AdminInterviewListItemResponse:
    row = await db.execute(
        select(
            Interview,
            Candidate.full_name,
            User.email,
        )
        .join(Candidate, Candidate.id == Interview.candidate_id)
        .join(User, User.id == Candidate.user_id)
        .where(Interview.id == interview_id)
    )
    payload = row.first()
    if not payload:
        raise ValueError("Interview not found")

    interview, candidate_name, candidate_email = payload
    if interview.status in {"created", "in_progress"}:
        raise ValueError("Interview is still in progress.")

    existing_report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )
    if existing_report:
        await db.delete(existing_report)

    interview.status = "report_processing"
    diagnostics = _read_report_diagnostics(interview) or {}
    diagnostics.update(
        {
            "last_phase": "admin_requeue",
            "last_status": "processing",
        }
    )
    state = dict(interview.interview_state or {})
    state["report_diagnostics"] = diagnostics
    interview.interview_state = state
    await db.commit()
    await db.refresh(interview)
    _schedule_report_generation(interview.id)

    return AdminInterviewListItemResponse(
        id=interview.id,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        target_role=interview.target_role,
        status=interview.status,
        language=interview.language,
        created_at=interview.created_at,
        completed_at=interview.completed_at,
        report_id=None,
        overall_score=None,
        hiring_recommendation=None,
        processing_state="processing",
    )


async def create_admin_audit_log(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: str | None,
    summary: str,
    metadata_json: dict | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            metadata_json=metadata_json,
        )
    )
    await db.commit()


async def list_admin_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 50,
) -> AdminUserListResponse:
    stmt = select(User).order_by(desc(User.created_at)).limit(min(max(limit, 1), 100))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(User.email.ilike(like))
    rows = (await db.execute(stmt)).scalars().all()
    return AdminUserListResponse(
        items=[
            AdminUserListItemResponse(
                id=row.id,
                email=row.email,
                role=row.role,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


async def set_admin_user_active(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    user_id: uuid.UUID,
    is_active: bool,
) -> AdminUserListItemResponse:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ValueError("User not found")
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    await create_admin_audit_log(
        db,
        actor_user_id=actor_user_id,
        action="user_status_changed",
        entity_type="user",
        entity_id=str(user.id),
        summary=f"{'Activated' if is_active else 'Deactivated'} user {user.email}",
        metadata_json={"is_active": is_active, "role": user.role},
    )
    return AdminUserListItemResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


async def list_admin_companies(
    db: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 50,
) -> AdminCompanyListResponse:
    owner_email_sq = select(User.email).where(User.id == Company.owner_user_id).scalar_subquery()
    member_count_sq = (
        select(func.count())
        .select_from(CompanyMember)
        .where(CompanyMember.company_id == Company.id)
        .scalar_subquery()
    )
    stmt = (
        select(
            Company.id,
            Company.name,
            Company.is_active,
            Company.created_at,
            owner_email_sq.label("owner_email"),
            member_count_sq.label("member_count"),
        )
        .order_by(desc(Company.created_at))
        .limit(min(max(limit, 1), 100))
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Company.name.ilike(like))
    rows = (await db.execute(stmt)).all()
    return AdminCompanyListResponse(
        items=[
            AdminCompanyListItemResponse(
                id=row.id,
                name=row.name,
                owner_email=row.owner_email,
                is_active=row.is_active,
                member_count=int(row.member_count or 0),
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


async def set_admin_company_active(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    company_id: uuid.UUID,
    is_active: bool,
) -> AdminCompanyListItemResponse:
    company = await db.scalar(select(Company).where(Company.id == company_id))
    if not company:
        raise ValueError("Company not found")
    company.is_active = is_active
    await db.commit()
    await db.refresh(company)

    owner_email = await db.scalar(select(User.email).where(User.id == company.owner_user_id))
    member_count = await db.scalar(
        select(func.count()).select_from(CompanyMember).where(CompanyMember.company_id == company.id)
    ) or 0
    await create_admin_audit_log(
        db,
        actor_user_id=actor_user_id,
        action="company_status_changed",
        entity_type="company",
        entity_id=str(company.id),
        summary=f"{'Activated' if is_active else 'Deactivated'} company {company.name}",
        metadata_json={"is_active": is_active, "owner_email": owner_email},
    )
    return AdminCompanyListItemResponse(
        id=company.id,
        name=company.name,
        owner_email=owner_email,
        is_active=company.is_active,
        member_count=int(member_count),
        created_at=company.created_at,
    )


async def list_admin_reports(
    db: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 50,
) -> AdminReportListResponse:
    stmt = (
        select(
            AssessmentReport.id,
            Candidate.full_name,
            User.email,
            Interview.target_role,
            AssessmentReport.overall_score,
            AssessmentReport.hiring_recommendation,
            AssessmentReport.created_at,
        )
        .join(Candidate, Candidate.id == AssessmentReport.candidate_id)
        .join(User, User.id == Candidate.user_id)
        .join(Interview, Interview.id == AssessmentReport.interview_id)
        .order_by(desc(AssessmentReport.created_at))
        .limit(min(max(limit, 1), 100))
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((Candidate.full_name.ilike(like)) | (User.email.ilike(like)))
    rows = (await db.execute(stmt)).all()
    return AdminReportListResponse(
        items=[
            AdminReportListItemResponse(
                id=row.id,
                candidate_name=row.full_name,
                candidate_email=row.email,
                target_role=row.target_role,
                overall_score=row.overall_score,
                hiring_recommendation=row.hiring_recommendation,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


async def list_admin_audit_logs(
    db: AsyncSession,
    *,
    limit: int = 100,
) -> AdminAuditLogListResponse:
    rows = (
        await db.execute(
            select(
                AdminAuditLog.id,
                User.email,
                AdminAuditLog.action,
                AdminAuditLog.entity_type,
                AdminAuditLog.entity_id,
                AdminAuditLog.summary,
                AdminAuditLog.metadata_json,
                AdminAuditLog.created_at,
            )
            .join(User, User.id == AdminAuditLog.actor_user_id)
            .order_by(desc(AdminAuditLog.created_at))
            .limit(min(max(limit, 1), 200))
        )
    ).all()
    return AdminAuditLogListResponse(
        items=[
            AdminAuditLogItemResponse(
                id=row.id,
                actor_email=row.email,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                summary=row.summary,
                metadata_json=row.metadata_json,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )
