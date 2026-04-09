import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_company, get_current_company_admin, get_current_company_recruiter, get_db
from app.models.company import Company
from app.models.interview import Interview
from app.models.user import User
from app.schemas.company import (
    AnalyticsFunnelResponse,
    AnalyticsOverviewResponse,
    AnalyticsSalaryResponse,
    CandidateActivityResponse,
    CompanyAISettingsResponse,
    CompanyAISettingsUpdateRequest,
    CandidateDetailResponse,
    CandidateListItemResponse,
    CandidateNoteCreateRequest,
    CandidateNoteResponse,
    HireOutcomeRequest,
    HireOutcomeResponse,
    ShortlistCreateRequest,
    ShortlistSummaryResponse,
)
from app.schemas.interview import InterviewReplayResponse
from app.schemas.interview import ProctoringTimelineResponse
from app.schemas.report import AssessmentReportResponse
from app.schemas.template import TemplateCreateRequest, TemplateResponse
from app.services.company_service import (
    get_analytics_funnel,
    get_analytics_overview,
    get_candidate_detail,
    get_company_report,
    get_salary_analytics,
    list_verified_candidates,
)
from app.services.company_settings_service import (
    get_company_ai_settings_response,
    update_company_ai_settings,
)
from app.services.candidate_access_service import (
    create_share_link_access_request,
    get_share_link_access_status,
)
from app.services.collaboration_service import (
    create_candidate_note,
    list_candidate_activity,
    list_candidate_notes,
    log_candidate_activity,
)
from app.services.hire_outcome_service import get_hire_outcome, set_hire_outcome
from app.services.interview_service import get_interview_replay
from app.services.interview_service import build_proctoring_timeline_response
from app.services.member_service import (
    MemberAlreadyExistsError,
    RoleConflictError,
    invite_member,
    list_members,
    remove_member,
)
from app.services.assessment_invite_service import (
    create_assessment,
    delete_assessment,
    get_current_assessment_module_payload,
    list_company_assessments,
)
from app.services.shortlist_service import (
    add_candidate_to_shortlist,
    create_shortlist,
    delete_shortlist,
    list_shortlists,
    remove_candidate_from_shortlist,
)
from app.services.template_service import (
    create_template,
    delete_template,
    list_company_templates,
)

router = APIRouter(prefix="/company", tags=["company"])


class ShareLinkAccessStatusResponse(BaseModel):
    candidate_id: uuid.UUID
    full_name: str
    request_status: str | None = None
    can_open_company_workspace: bool = False


class ShareLinkRequestResponse(BaseModel):
    candidate_id: uuid.UUID
    full_name: str
    request_status: str
    can_open_company_workspace: bool = False


@router.get("/candidates", response_model=list[CandidateListItemResponse])
async def get_candidates(
    q: str | None = None,
    role: str | None = None,
    skills: list[str] | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0, le=10),
    recommendation: str | None = None,
    salary_min: int | None = Query(default=None, ge=0),
    salary_max: int | None = Query(default=None, ge=0),
    hire_outcome: str | None = None,
    shortlist_id: uuid.UUID | None = None,
    sort: str = Query(default="score_desc", pattern="^(score_desc|score_asc|latest|salary_asc|salary_desc)$"),
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_verified_candidates(
        db,
        company_id=company.id,
        q=q,
        role=role,
        skills=skills,
        min_score=min_score,
        recommendation=recommendation,
        salary_min=salary_min,
        salary_max=salary_max,
        hire_outcome=hire_outcome,
        shortlist_id=shortlist_id,
        sort=sort,
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailResponse)
async def get_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    result = await get_candidate_detail(db, candidate_id, company_id=company.id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return result


@router.get("/share-links/{share_token}", response_model=ShareLinkAccessStatusResponse)
async def get_share_link_status(
    share_token: str,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    candidate, request, can_open_company_workspace = await get_share_link_access_status(db, share_token, company.id)
    return ShareLinkAccessStatusResponse(
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        request_status=request.status if request else None,
        can_open_company_workspace=can_open_company_workspace,
    )


@router.post("/share-links/{share_token}/request-access", response_model=ShareLinkRequestResponse)
async def request_share_link_access(
    share_token: str,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    user, company = user_and_company
    request = await create_share_link_access_request(db, share_token, company.id, user.id)
    await log_candidate_activity(
        db,
        company_id=company.id,
        candidate_id=request.candidate_id,
        actor_user_id=user.id,
        activity_type="access_requested",
        summary="Requested candidate workspace access",
        metadata={"access_request_id": str(request.id), "status": request.status},
    )
    candidate, refreshed_request, can_open_company_workspace = await get_share_link_access_status(db, share_token, company.id)
    return ShareLinkRequestResponse(
        candidate_id=request.candidate_id,
        full_name=candidate.full_name,
        request_status=refreshed_request.status if refreshed_request else request.status,
        can_open_company_workspace=can_open_company_workspace,
    )


@router.post("/candidates/{candidate_id}/outcome", response_model=HireOutcomeResponse)
async def set_candidate_outcome(
    candidate_id: uuid.UUID,
    body: HireOutcomeRequest,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    user, company, _ = context
    try:
        record = await set_hire_outcome(db, company.id, candidate_id, body.outcome, body.notes, actor_user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return HireOutcomeResponse(outcome=record.outcome, notes=record.notes, updated_at=record.updated_at)


@router.get("/candidates/{candidate_id}/outcome", response_model=HireOutcomeResponse)
async def get_candidate_outcome(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    record = await get_hire_outcome(db, company.id, candidate_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No outcome recorded")
    return HireOutcomeResponse(outcome=record.outcome, notes=record.notes, updated_at=record.updated_at)


@router.get("/interviews/{interview_id}/replay", response_model=InterviewReplayResponse)
async def get_replay(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    user, company = user_and_company
    result = await get_interview_replay(db, interview_id, company.id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    await log_candidate_activity(
        db,
        company_id=company.id,
        candidate_id=result.candidate_id,
        actor_user_id=user.id,
        activity_type="replay_viewed",
        summary="Viewed interview replay",
        metadata={"interview_id": str(interview_id)},
    )
    return result


@router.get("/reports/{report_id}", response_model=AssessmentReportResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    user, company = user_and_company
    report = await get_company_report(db, report_id, company.id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    await log_candidate_activity(
        db,
        company_id=company.id,
        candidate_id=report.candidate_id,
        actor_user_id=user.id,
        activity_type="report_viewed",
        summary="Viewed assessment report",
        metadata={"report_id": str(report.id)},
    )
    return report


@router.get("/reports/{report_id}/proctoring-timeline", response_model=ProctoringTimelineResponse)
async def get_report_proctoring_timeline(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    report = await get_company_report(db, report_id, company.id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    interview = await db.scalar(select(Interview).where(Interview.id == report.interview_id))
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    return build_proctoring_timeline_response(
        interview_id=interview.id,
        report_id=report.id,
        signals=interview.behavioral_signals,
    )


@router.get("/shortlists", response_model=list[ShortlistSummaryResponse])
async def get_shortlists(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_shortlists(db, company.id)


@router.post("/shortlists", response_model=ShortlistSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_company_shortlist(
    body: ShortlistCreateRequest,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    user, company, _ = context
    return await create_shortlist(db, company.id, user.id, body.name)


@router.delete("/shortlists/{shortlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company_shortlist(
    shortlist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    _, company, _ = context
    await delete_shortlist(db, shortlist_id, company.id)


@router.post("/shortlists/{shortlist_id}/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_candidate_shortlist_membership(
    shortlist_id: uuid.UUID,
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    user, company, _ = context
    await add_candidate_to_shortlist(db, shortlist_id, candidate_id, company.id, actor_user_id=user.id)


@router.delete("/shortlists/{shortlist_id}/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate_shortlist_membership(
    shortlist_id: uuid.UUID,
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    user, company, _ = context
    await remove_candidate_from_shortlist(db, shortlist_id, candidate_id, company.id, actor_user_id=user.id)


@router.get("/candidates/{candidate_id}/notes", response_model=list[CandidateNoteResponse])
async def get_candidate_notes(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_candidate_notes(db, company.id, candidate_id)


@router.post("/candidates/{candidate_id}/notes", response_model=CandidateNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate_shared_note(
    candidate_id: uuid.UUID,
    body: CandidateNoteCreateRequest,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    user, company, _ = context
    return await create_candidate_note(db, company.id, candidate_id, user.id, body.body)


@router.get("/candidates/{candidate_id}/activity", response_model=list[CandidateActivityResponse])
async def get_candidate_activity(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_candidate_activity(db, company.id, candidate_id)


@router.get("/analytics/overview", response_model=AnalyticsOverviewResponse)
async def company_analytics_overview(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await get_analytics_overview(db, company.id)


@router.get("/analytics/funnel", response_model=AnalyticsFunnelResponse)
async def company_analytics_funnel(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await get_analytics_funnel(db, company.id)


@router.get("/analytics/salary", response_model=AnalyticsSalaryResponse)
async def company_analytics_salary(
    role: str | None = None,
    shortlist_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await get_salary_analytics(db, company.id, role=role, shortlist_id=shortlist_id)


@router.get("/settings/ai", response_model=CompanyAISettingsResponse)
async def get_company_ai_settings(
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return get_company_ai_settings_response(company)


@router.put("/settings/ai", response_model=CompanyAISettingsResponse)
async def put_company_ai_settings(
    body: CompanyAISettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    context: tuple[User, Company, str] = Depends(get_current_company_recruiter),
):
    _, company, role = context
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the company admin can manage AI settings")
    return await update_company_ai_settings(
        db,
        company=company,
        updates=body.model_dump(exclude_unset=True),
    )


# ── Team Members ───────────────────────────────────────────────────────────────

class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "recruiter"


class MemberResponse(BaseModel):
    member_id: str | None
    user_id: str
    email: str
    role: str
    created_at: str


class InviteMemberResponse(BaseModel):
    member: MemberResponse
    temp_password: str | None


@router.get("/members", response_model=list[MemberResponse])
async def get_members(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_members(db, company.id)


@router.post("/members/invite", response_model=InviteMemberResponse, status_code=status.HTTP_201_CREATED)
async def invite_company_member(
    body: InviteMemberRequest,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    user, company = user_and_company
    # Only admin (owner) can invite
    if user.role != "company_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the company admin can invite members")
    try:
        member, temp_password = await invite_member(db, company.id, body.email, user.id, body.role)
    except MemberAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RoleConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return InviteMemberResponse(
        member=MemberResponse(
            member_id=str(member.id),
            user_id=str(member.user_id),
            email=body.email,
            role=member.role,
            created_at=member.created_at.isoformat(),
        ),
        temp_password=temp_password,
    )


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_company_member(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    current_user, company = user_and_company
    if current_user.role != "company_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the company admin can remove members")
    await remove_member(db, company.id, user_id, current_user.id)


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    templates = await list_company_templates(db, company.id)
    return [
        TemplateResponse(
            template_id=t.id,
            company_id=t.company_id,
            name=t.name,
            target_role=t.target_role,
            questions=t.questions,
            description=t.description,
            is_public=t.is_public,
            created_at=t.created_at,
        )
        for t in templates
    ]


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_template(
    body: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
    _admin: User = Depends(get_current_company_admin),
):
    _, company = user_and_company
    t = await create_template(
        db,
        company_id=company.id,
        name=body.name,
        target_role=body.target_role,
        questions=body.questions,
        description=body.description,
        is_public=body.is_public,
    )
    return TemplateResponse(
        template_id=t.id,
        company_id=t.company_id,
        name=t.name,
        target_role=t.target_role,
        questions=t.questions,
        description=t.description,
        is_public=t.is_public,
        created_at=t.created_at,
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
    _admin: User = Depends(get_current_company_admin),
):
    _, company = user_and_company
    await delete_template(db, template_id, company.id)


# ── Employee Assessments ───────────────────────────────────────────────────────

class CreateAssessmentModulePlanItemRequest(BaseModel):
    module_id: str | None = None
    module_type: str
    title: str | None = None
    config: dict[str, Any] | None = None


class CreateAssessmentRequest(BaseModel):
    employee_email: EmailStr
    employee_name: str
    target_role: str
    assessment_type: str = "employee_internal"
    template_id: uuid.UUID | None = None
    deadline_at: datetime | None = None
    expires_at: datetime | None = None
    branding_name: str | None = None
    branding_logo_url: str | None = None
    module_plan: list[CreateAssessmentModulePlanItemRequest] | None = None


class AssessmentModulePlanItemResponse(BaseModel):
    module_id: str
    module_type: str
    title: str
    status: str
    config: dict | None = None
    interview_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class AssessmentResponse(BaseModel):
    id: str
    employee_email: str
    employee_name: str
    assessment_type: str
    target_role: str
    template_id: str | None = None
    template_name: str | None = None
    status: str
    invite_token: str
    interview_id: str | None
    report_id: str | None
    deadline_at: str | None = None
    expires_at: str | None = None
    opened_at: str | None = None
    completed_at: str | None = None
    branding_name: str | None = None
    branding_logo_url: str | None = None
    module_plan: list[AssessmentModulePlanItemResponse]
    module_count: int
    current_module_index: int
    current_module_type: str | None = None
    created_at: str


@router.get("/assessments", response_model=list[AssessmentResponse])
async def get_assessments(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_company_assessments(db, company.id)


@router.post("/assessments", response_model=AssessmentResponse, status_code=status.HTTP_201_CREATED)
async def create_employee_assessment(
    body: CreateAssessmentRequest,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
    _admin: User = Depends(get_current_company_admin),
):
    user, company = user_and_company
    a = await create_assessment(
        db,
        company_id=company.id,
        created_by_user_id=user.id,
        employee_email=body.employee_email,
        employee_name=body.employee_name,
        target_role=body.target_role,
        assessment_type=body.assessment_type,
        template_id=body.template_id,
        module_plan=[
            item.model_dump(exclude_none=True)
            for item in body.module_plan
        ] if body.module_plan is not None else None,
        deadline_at=body.deadline_at,
        expires_at=body.expires_at,
        branding_name=body.branding_name,
        branding_logo_url=body.branding_logo_url,
    )
    module_plan, current_module_index, current_module = get_current_assessment_module_payload(a)
    return AssessmentResponse(
        id=str(a.id),
        employee_email=a.employee_email,
        employee_name=a.employee_name,
        assessment_type=a.assessment_type,
        target_role=a.target_role,
        template_id=str(a.template_id) if a.template_id else None,
        template_name=a.template.name if a.template else None,
        status=a.status,
        invite_token=a.invite_token,
        interview_id=None,
        report_id=None,
        deadline_at=a.deadline_at.isoformat() if a.deadline_at else None,
        expires_at=a.expires_at.isoformat() if a.expires_at else None,
        opened_at=a.opened_at.isoformat() if a.opened_at else None,
        completed_at=a.completed_at.isoformat() if a.completed_at else None,
        branding_name=a.branding_name,
        branding_logo_url=a.branding_logo_url,
        module_plan=[
            AssessmentModulePlanItemResponse(**item)
            for item in module_plan
        ],
        module_count=len(module_plan),
        current_module_index=current_module_index,
        current_module_type=current_module.get("module_type") if current_module else None,
        created_at=a.created_at.isoformat(),
    )


@router.delete("/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_assessment(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
    _admin: User = Depends(get_current_company_admin),
):
    _, company = user_and_company
    await delete_assessment(db, assessment_id, company.id)
