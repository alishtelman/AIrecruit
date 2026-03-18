import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_company, get_current_company_admin, get_db
from app.models.company import Company
from app.models.user import User
from app.schemas.company import (
    CandidateDetailResponse,
    CandidateListItemResponse,
    HireOutcomeRequest,
    HireOutcomeResponse,
)
from app.schemas.interview import InterviewReplayResponse
from app.schemas.report import AssessmentReportResponse
from app.schemas.template import TemplateCreateRequest, TemplateResponse
from app.services.company_service import get_candidate_detail, get_company_report, list_verified_candidates
from app.services.hire_outcome_service import get_hire_outcome, set_hire_outcome
from app.services.interview_service import get_interview_replay
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
    list_company_assessments,
)
from app.services.template_service import (
    create_template,
    delete_template,
    list_company_templates,
)

router = APIRouter(prefix="/company", tags=["company"])


@router.get("/candidates", response_model=list[CandidateListItemResponse])
async def get_candidates(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    return await list_verified_candidates(db, company_id=company.id)


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


@router.post("/candidates/{candidate_id}/outcome", response_model=HireOutcomeResponse)
async def set_candidate_outcome(
    candidate_id: uuid.UUID,
    body: HireOutcomeRequest,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    try:
        record = await set_hire_outcome(db, company.id, candidate_id, body.outcome, body.notes)
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
    _, company = user_and_company
    result = await get_interview_replay(db, interview_id, company.id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    return result


@router.get("/reports/{report_id}", response_model=AssessmentReportResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    report = await get_company_report(db, report_id, company.id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


# ── Team Members ───────────────────────────────────────────────────────────────

class InviteMemberRequest(BaseModel):
    email: EmailStr


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
        member, temp_password = await invite_member(db, company.id, body.email, user.id)
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

class CreateAssessmentRequest(BaseModel):
    employee_email: EmailStr
    employee_name: str
    target_role: str


class AssessmentResponse(BaseModel):
    id: str
    employee_email: str
    employee_name: str
    target_role: str
    status: str
    invite_token: str
    interview_id: str | None
    report_id: str | None
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
):
    user, company = user_and_company
    a = await create_assessment(
        db,
        company_id=company.id,
        created_by_user_id=user.id,
        employee_email=body.employee_email,
        employee_name=body.employee_name,
        target_role=body.target_role,
    )
    return AssessmentResponse(
        id=str(a.id),
        employee_email=a.employee_email,
        employee_name=a.employee_name,
        target_role=a.target_role,
        status=a.status,
        invite_token=a.invite_token,
        interview_id=None,
        report_id=None,
        created_at=a.created_at.isoformat(),
    )


@router.delete("/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_assessment(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    await delete_assessment(db, assessment_id, company.id)
