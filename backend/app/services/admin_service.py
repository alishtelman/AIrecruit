import time
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.runtime_status import get_ai_runtime_status, record_ai_error, record_ai_success
from app.models.admin_audit_log import AdminAuditLog
from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.company_assessment import CompanyAssessment
from app.models.company_member import CompanyMember
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.user import User
from app.schemas.admin import (
    AdminAuditLogItemResponse,
    AdminAuditLogListResponse,
    AdminCompanyListItemResponse,
    AdminCompanyListResponse,
    AdminDailyTrendPointResponse,
    AdminLLMDiagnosticsResponse,
    AdminLLMPingResponse,
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
from app.schemas.report import AssessmentReportResponse
from app.services.interview_service import _read_report_diagnostics, _schedule_report_generation
from app.services.platform_settings_service import get_platform_settings_payload, update_platform_settings


def _daily_bucket_template(days: int = 7) -> dict[str, dict[str, int]]:
    start = date.today() - timedelta(days=days - 1)
    return {
        (start + timedelta(days=offset)).isoformat(): {
            "interviews_started": 0,
            "reports_generated": 0,
            "candidates_created": 0,
            "companies_created": 0,
        }
        for offset in range(days)
    }


def _bucket_created_at(rows: list[datetime], buckets: dict[str, dict[str, int]], field: str) -> None:
    for created_at in rows:
        key = created_at.date().isoformat()
        if key in buckets:
            buckets[key][field] += 1


async def get_admin_overview(db: AsyncSession) -> AdminOverviewResponse:
    start_date = date.today() - timedelta(days=6)
    start_dt = datetime.combine(start_date, datetime.min.time())

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    active_candidates = await db.scalar(select(func.count()).select_from(Candidate)) or 0
    candidates_added_7d = await db.scalar(
        select(func.count()).select_from(Candidate).where(Candidate.created_at >= start_dt)
    ) or 0
    total_companies = await db.scalar(select(func.count()).select_from(Company)) or 0
    active_companies = await db.scalar(
        select(func.count()).select_from(Company).where(Company.is_active.is_(True))
    ) or 0
    companies_added_7d = await db.scalar(
        select(func.count()).select_from(Company).where(Company.created_at >= start_dt)
    ) or 0
    company_members = await db.scalar(select(func.count()).select_from(CompanyMember)) or 0
    interviews_total = await db.scalar(select(func.count()).select_from(Interview)) or 0
    interviews_started_7d = await db.scalar(
        select(func.count()).select_from(Interview).where(Interview.created_at >= start_dt)
    ) or 0
    interviews_in_progress = await db.scalar(
        select(func.count()).select_from(Interview).where(Interview.status == "in_progress")
    ) or 0
    interviews_completed = await db.scalar(
        select(func.count()).select_from(Interview).where(
            Interview.status.in_(("completed", "report_generated"))
        )
    ) or 0
    interviews_failed = await db.scalar(
        select(func.count()).select_from(Interview).where(Interview.status == "failed")
    ) or 0
    report_processing = await db.scalar(
        select(func.count())
        .select_from(Interview)
        .outerjoin(AssessmentReport, AssessmentReport.interview_id == Interview.id)
        .where(
            Interview.status.in_(("completed", "report_processing")),
            AssessmentReport.id.is_(None),
        )
    ) or 0
    reports_generated = await db.scalar(select(func.count()).select_from(AssessmentReport)) or 0
    reports_generated_7d = await db.scalar(
        select(func.count()).select_from(AssessmentReport).where(AssessmentReport.created_at >= start_dt)
    ) or 0
    average_overall_score = await db.scalar(select(func.avg(AssessmentReport.overall_score)))
    completion_rate_pct = round((interviews_completed / interviews_total) * 100, 1) if interviews_total else 0.0

    buckets = _daily_bucket_template()
    _bucket_created_at(
        list((await db.execute(select(Interview.created_at).where(Interview.created_at >= start_dt))).scalars()),
        buckets,
        "interviews_started",
    )
    _bucket_created_at(
        list((await db.execute(select(AssessmentReport.created_at).where(AssessmentReport.created_at >= start_dt))).scalars()),
        buckets,
        "reports_generated",
    )
    _bucket_created_at(
        list((await db.execute(select(Candidate.created_at).where(Candidate.created_at >= start_dt))).scalars()),
        buckets,
        "candidates_created",
    )
    _bucket_created_at(
        list((await db.execute(select(Company.created_at).where(Company.created_at >= start_dt))).scalars()),
        buckets,
        "companies_created",
    )
    daily_trends = [
        AdminDailyTrendPointResponse(date=day, **values)
        for day, values in buckets.items()
    ]

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
            candidates_added_7d=candidates_added_7d,
            total_companies=total_companies,
            active_companies=active_companies,
            companies_added_7d=companies_added_7d,
            company_members=company_members,
            interviews_total=interviews_total,
            interviews_started_7d=interviews_started_7d,
            interviews_in_progress=interviews_in_progress,
            interviews_completed=interviews_completed,
            interviews_failed=interviews_failed,
            completion_rate_pct=completion_rate_pct,
            report_processing=report_processing,
            reports_generated=reports_generated,
            reports_generated_7d=reports_generated_7d,
            average_overall_score=round(float(average_overall_score), 1) if average_overall_score is not None else None,
        ),
        runtime=AdminRuntimeStatusResponse(
            app_env=settings.APP_ENV,
            rate_limit_enabled=settings.rate_limit_enabled,
            platform_admin_bootstrap_enabled=settings.platform_admin_bootstrap_enabled,
        ),
        daily_trends=daily_trends,
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _runtime_event_payload(value: object) -> dict | None:
    return value if isinstance(value, dict) else None


async def get_admin_llm_diagnostics(db: AsyncSession) -> AdminLLMDiagnosticsResponse:
    platform_settings = await get_platform_settings_payload(db)
    runtime_status = get_ai_runtime_status()
    api_key_available = bool(platform_settings.get("llm_api_key_available"))
    return AdminLLMDiagnosticsResponse(
        provider=str(platform_settings.get("llm_provider") or "openai"),
        interviewer_model=str(platform_settings.get("interviewer_model") or "unknown"),
        assessor_model=str(platform_settings.get("assessor_model") or "unknown"),
        configured=api_key_available and not platform_settings.get("llm_configuration_warning"),
        api_key_available=api_key_available,
        required_api_key=platform_settings.get("llm_required_api_key"),
        configuration_warning=platform_settings.get("llm_configuration_warning"),
        timeout_seconds=int(platform_settings.get("llm_timeout_seconds") or 30),
        max_retries=int(platform_settings.get("llm_max_retries") or 0),
        runtime_provider=str(runtime_status.get("provider") or "unknown"),
        runtime_model=str(runtime_status.get("model") or "unknown"),
        runtime_api_key_present=bool(runtime_status.get("api_key_present")),
        last_success=_runtime_event_payload(runtime_status.get("last_success")),
        last_error=_runtime_event_payload(runtime_status.get("last_error")),
        checked_at=_utc_now(),
    )


async def run_admin_llm_ping(db: AsyncSession) -> AdminLLMPingResponse:
    platform_settings = await get_platform_settings_payload(db)
    provider_name = str(platform_settings.get("llm_provider") or "openai")
    model_name = str(platform_settings.get("interviewer_model") or settings.OPENAI_MODEL)
    timeout_seconds = min(float(platform_settings.get("llm_timeout_seconds") or 30), 20.0)
    created_at = _utc_now()

    if provider_name != "openai":
        return AdminLLMPingResponse(
            ok=False,
            provider=provider_name,
            model=model_name,
            status="unsupported_provider",
            error="Only OpenAI is supported.",
            created_at=created_at,
        )

    if not settings.OPENAI_API_KEY:
        return AdminLLMPingResponse(
            ok=False,
            provider=provider_name,
            model=model_name,
            status="missing_api_key",
            error="OPENAI_API_KEY is not configured.",
            created_at=created_at,
        )

    provider = OpenAIProvider(
        api_key=settings.OPENAI_API_KEY,
        default_model=model_name,
        reasoning_effort=settings.OPENAI_REASONING_EFFORT,
        base_url=settings.OPENAI_BASE_URL,
    )
    start = time.monotonic()
    try:
        result = await provider.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are a production health check. Reply with exactly: OK",
                },
                {"role": "user", "content": "Return OK if this LLM request works."},
            ],
            model=model_name,
            temperature=0.0,
            max_tokens=16,
            timeout=timeout_seconds,
        )
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        response_preview = str(result.text or "").strip()[:120]
        record_ai_success(
            component="admin_llm_ping",
            provider=provider_name,
            model=result.actual_model_used or model_name,
            note=f"latency_ms={latency_ms}",
        )
        return AdminLLMPingResponse(
            ok=True,
            provider=provider_name,
            model=result.actual_model_used or model_name,
            status="ok",
            latency_ms=latency_ms,
            response_preview=response_preview,
            created_at=created_at,
        )
    except Exception as exc:  # noqa: BLE001 - admin diagnostics should return structured failure
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        error = str(exc)
        record_ai_error(
            component="admin_llm_ping",
            provider=provider_name,
            model=model_name,
            error=error,
        )
        return AdminLLMPingResponse(
            ok=False,
            provider=provider_name,
            model=model_name,
            status="error",
            latency_ms=latency_ms,
            error=error[:500],
            created_at=created_at,
        )
    finally:
        await provider.aclose()


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
    if actor_user_id == user.id and not is_active:
        raise ValueError("Platform admin cannot deactivate their own account.")
    if user.role == "platform_admin" and not is_active:
        active_admin_count = await db.scalar(
            select(func.count()).select_from(User).where(
                User.role == "platform_admin",
                User.is_active.is_(True),
            )
        ) or 0
        if active_admin_count <= 1:
            raise ValueError("Cannot deactivate the last active platform admin.")
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
    status: str | None = None,
    limit: int = 50,
) -> AdminCompanyListResponse:
    owner_email_sq = select(User.email).where(User.id == Company.owner_user_id).scalar_subquery()
    member_count_sq = (
        select(func.count())
        .select_from(CompanyMember)
        .where(CompanyMember.company_id == Company.id)
        .scalar_subquery()
    )
    assessments_total_sq = (
        select(func.count())
        .select_from(CompanyAssessment)
        .where(CompanyAssessment.company_id == Company.id)
        .scalar_subquery()
    )
    assessments_in_progress_sq = (
        select(func.count())
        .select_from(CompanyAssessment)
        .where(
            CompanyAssessment.company_id == Company.id,
            CompanyAssessment.status == "in_progress",
        )
        .scalar_subquery()
    )
    assessments_pending_sq = (
        select(func.count())
        .select_from(CompanyAssessment)
        .where(
            CompanyAssessment.company_id == Company.id,
            CompanyAssessment.status.in_(("pending", "opened")),
        )
        .scalar_subquery()
    )
    assessments_completed_sq = (
        select(func.count())
        .select_from(CompanyAssessment)
        .where(
            CompanyAssessment.company_id == Company.id,
            CompanyAssessment.status == "completed",
        )
        .scalar_subquery()
    )
    reports_generated_sq = (
        select(func.count())
        .select_from(AssessmentReport)
        .join(Interview, Interview.id == AssessmentReport.interview_id)
        .where(Interview.company_assessment_id.in_(
            select(CompanyAssessment.id).where(CompanyAssessment.company_id == Company.id)
        ))
        .scalar_subquery()
    )
    last_assessment_activity_sq = (
        select(func.max(CompanyAssessment.created_at))
        .where(CompanyAssessment.company_id == Company.id)
        .scalar_subquery()
    )
    stmt = (
        select(
            Company.id,
            Company.name,
            Company.is_active,
            Company.created_at,
            Company.updated_at,
            owner_email_sq.label("owner_email"),
            member_count_sq.label("member_count"),
            assessments_total_sq.label("assessments_total"),
            assessments_in_progress_sq.label("assessments_in_progress"),
            assessments_pending_sq.label("assessments_pending"),
            assessments_completed_sq.label("assessments_completed"),
            reports_generated_sq.label("reports_generated"),
            last_assessment_activity_sq.label("last_assessment_activity_at"),
        )
        .order_by(desc(Company.created_at))
        .limit(min(max(limit, 1), 100))
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((Company.name.ilike(like)) | (owner_email_sq.ilike(like)))
    if status == "active":
        stmt = stmt.where(Company.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(Company.is_active.is_(False))
    rows = (await db.execute(stmt)).all()
    return AdminCompanyListResponse(
        items=[
            AdminCompanyListItemResponse(
                id=row.id,
                name=row.name,
                owner_email=row.owner_email,
                is_active=row.is_active,
                member_count=int(row.member_count or 0),
                assessments_total=int(row.assessments_total or 0),
                assessments_in_progress=int(row.assessments_in_progress or 0),
                assessments_pending=int(row.assessments_pending or 0),
                assessments_completed=int(row.assessments_completed or 0),
                reports_generated=int(row.reports_generated or 0),
                last_activity_at=row.last_assessment_activity_at or row.updated_at or row.created_at,
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
        last_activity_at=company.updated_at or company.created_at,
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


async def get_admin_report(
    db: AsyncSession,
    report_id: uuid.UUID,
) -> AssessmentReportResponse:
    report = await db.scalar(select(AssessmentReport).where(AssessmentReport.id == report_id))
    if not report:
        raise ValueError("Report not found")
    return AssessmentReportResponse.model_validate(report)


async def list_admin_audit_logs(
    db: AsyncSession,
    *,
    q: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
) -> AdminAuditLogListResponse:
    stmt = (
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
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (User.email.ilike(like))
            | (AdminAuditLog.action.ilike(like))
            | (AdminAuditLog.entity_type.ilike(like))
            | (AdminAuditLog.entity_id.ilike(like))
            | (AdminAuditLog.summary.ilike(like))
        )
    if action:
        stmt = stmt.where(AdminAuditLog.action == action.strip())
    if entity_type:
        stmt = stmt.where(AdminAuditLog.entity_type == entity_type.strip())

    rows = (await db.execute(stmt)).all()
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
