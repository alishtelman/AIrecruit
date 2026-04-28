import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_platform_admin, get_db
from app.models.user import User
from app.schemas.admin import (
    AdminActivationUpdateRequest,
    AdminAuditLogListResponse,
    AdminCompanyListItemResponse,
    AdminCompanyListResponse,
    AdminInterviewListItemResponse,
    AdminInterviewListResponse,
    AdminOverviewResponse,
    AdminReportListResponse,
    AdminUserListItemResponse,
    AdminUserListResponse,
    PlatformAISettingsUpdateRequest,
    PlatformSettingsResponse,
    PlatformSettingsUpdateRequest,
)
from app.services.admin_service import (
    admin_requeue_interview_report,
    create_admin_audit_log,
    get_admin_overview,
    get_admin_platform_settings,
    list_admin_audit_logs,
    list_admin_companies,
    list_admin_interviews,
    list_admin_reports,
    list_admin_users,
    set_admin_company_active,
    set_admin_user_active,
    update_admin_platform_settings,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_admin_overview(db)


@router.get("/platform-settings", response_model=PlatformSettingsResponse)
async def admin_platform_settings(
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_admin_platform_settings(db)


@router.put("/platform-settings", response_model=PlatformSettingsResponse)
async def update_admin_platform(
    body: PlatformSettingsUpdateRequest,
    current_user: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    payload = await update_admin_platform_settings(
        db,
        candidate_registration_enabled=body.candidate_registration_enabled,
        company_registration_enabled=body.company_registration_enabled,
        employee_invites_enabled=body.employee_invites_enabled,
        maintenance_mode_enabled=body.maintenance_mode_enabled,
    )
    changed = body.model_dump(exclude_none=True)
    if changed:
        await create_admin_audit_log(
            db,
            actor_user_id=current_user.id,
            action="platform_settings_updated",
            entity_type="platform_settings",
            entity_id="1",
            summary="Updated global platform settings",
            metadata_json=changed,
        )
    return payload


@router.put("/ai-settings", response_model=PlatformSettingsResponse)
async def update_admin_ai_settings(
    body: PlatformAISettingsUpdateRequest,
    current_user: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = await update_admin_platform_settings(
            db,
            proctoring_policy_mode=body.proctoring_policy_mode,
            interviewer_model_preference=body.interviewer_model_preference,
            assessor_model_preference=body.assessor_model_preference,
            llm_provider=body.llm_provider,
            interviewer_model=body.interviewer_model,
            assessor_model=body.assessor_model,
            interviewer_prompt_override=body.interviewer_prompt_override,
            assessor_prompt_override=body.assessor_prompt_override,
            llm_timeout_seconds=body.llm_timeout_seconds,
            llm_max_retries=body.llm_max_retries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    changed = body.model_dump(exclude_none=True)
    if changed:
        safe_changed = {
            key: ("changed" if key.endswith("_prompt_override") else value)
            for key, value in changed.items()
        }
        await create_admin_audit_log(
            db,
            actor_user_id=current_user.id,
            action="platform_ai_settings_updated",
            entity_type="platform_settings",
            entity_id="1",
            summary="Updated global AI defaults",
            metadata_json=safe_changed,
        )
    return payload


@router.get("/interviews", response_model=AdminInterviewListResponse)
async def admin_interviews(
    q: str | None = None,
    status: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=100),
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await list_admin_interviews(db, q=q, status=status, limit=limit)


@router.post("/interviews/{interview_id}/requeue-report", response_model=AdminInterviewListItemResponse)
async def admin_requeue_report(
    interview_id: uuid.UUID,
    current_user: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = await admin_requeue_interview_report(db, interview_id)
        await create_admin_audit_log(
            db,
            actor_user_id=current_user.id,
            action="report_requeued",
            entity_type="interview",
            entity_id=str(interview_id),
            summary=f"Requeued report generation for interview {interview_id}",
            metadata_json={"interview_id": str(interview_id)},
        )
        return payload
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=409, detail=detail)


@router.get("/users", response_model=AdminUserListResponse)
async def admin_users(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await list_admin_users(db, q=q, limit=limit)


@router.put("/users/{user_id}/status", response_model=AdminUserListItemResponse)
async def admin_set_user_status(
    user_id: uuid.UUID,
    body: AdminActivationUpdateRequest,
    current_user: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await set_admin_user_active(
            db,
            actor_user_id=current_user.id,
            user_id=user_id,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/companies", response_model=AdminCompanyListResponse)
async def admin_companies(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await list_admin_companies(db, q=q, limit=limit)


@router.put("/companies/{company_id}/status", response_model=AdminCompanyListItemResponse)
async def admin_set_company_status(
    company_id: uuid.UUID,
    body: AdminActivationUpdateRequest,
    current_user: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await set_admin_company_active(
            db,
            actor_user_id=current_user.id,
            company_id=company_id,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reports", response_model=AdminReportListResponse)
async def admin_reports(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await list_admin_reports(db, q=q, limit=limit)


@router.get("/audit-log", response_model=AdminAuditLogListResponse)
async def admin_audit_log(
    limit: int = Query(default=100, ge=1, le=200),
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await list_admin_audit_logs(db, limit=limit)
