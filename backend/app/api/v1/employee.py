"""
Employee assessment invite endpoints.

GET  /api/v1/employee/invite/{token}        — public, returns invite info
POST /api/v1/employee/invite/{token}/start  — authenticated candidate, starts interview
"""
from fastapi import APIRouter, Depends, HTTPException, status
from groq import AuthenticationError as GroqAuthenticationError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate, get_db
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.user import User
from app.services.assessment_invite_service import (
    can_start_current_assessment_module_via_interview,
    get_assessment_by_token,
    get_assessment_for_invite_view,
    get_current_assessment_module_payload,
    link_interview_to_assessment,
)
from app.services.interview_service import build_assessment_module_preview

router = APIRouter(prefix="/employee", tags=["employee"])

_ROLE_LABELS = {
    "backend_engineer": "Backend Engineer",
    "frontend_engineer": "Frontend Engineer",
    "qa_engineer": "QA Engineer",
    "devops_engineer": "DevOps Engineer",
    "data_scientist": "Data Scientist",
    "product_manager": "Product Manager",
    "mobile_engineer": "Mobile Engineer",
    "designer": "UX/UI Designer",
}


class InviteInfoResponse(BaseModel):
    assessment_id: str
    employee_name: str
    employee_email: str
    assessment_type: str
    target_role: str
    role_label: str
    status: str
    company_name: str
    template_name: str | None = None
    deadline_at: str | None = None
    expires_at: str | None = None
    branding_name: str | None = None
    branding_logo_url: str | None = None
    module_plan: list[dict]
    module_count: int
    current_module_index: int
    current_module_type: str | None = None
    current_module_title: str | None = None
    current_module_preview: dict | None = None
    active_interview_id: str | None = None
    can_start_current_module: bool = False


class StartAssessmentRequest(BaseModel):
    language: str = "ru"


class StartAssessmentResponse(BaseModel):
    interview_id: str
    assessment_id: str


@router.get("/invite/{token}", response_model=InviteInfoResponse)
async def get_invite_info(token: str, language: str = "ru", db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns invite details so employee can see who invited them."""
    from fastapi import HTTPException, status
    assessment = await get_assessment_for_invite_view(db, token)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or expired")

    module_plan, current_module_index, current_module = get_current_assessment_module_payload(assessment)
    active_interview_id: str | None = None
    has_active_interview = False
    if assessment.interview_id:
        interview = await db.scalar(select(Interview).where(Interview.id == assessment.interview_id))
        if interview and interview.status in {"created", "in_progress"}:
            active_interview_id = str(interview.id)
            has_active_interview = True
    current_module_preview = build_assessment_module_preview(
        module_type=current_module.get("module_type") if current_module else None,
        target_role=assessment.target_role,
        language="en" if str(language).strip().lower() == "en" else "ru",
        module_config=current_module.get("config") if current_module else None,
    )

    return InviteInfoResponse(
        assessment_id=str(assessment.id),
        employee_name=assessment.employee_name,
        employee_email=assessment.employee_email,
        assessment_type=assessment.assessment_type,
        target_role=assessment.target_role,
        role_label=_ROLE_LABELS.get(assessment.target_role, assessment.target_role),
        status=assessment.status,
        company_name=assessment.company.name,
        template_name=assessment.template.name if assessment.template else None,
        deadline_at=assessment.deadline_at.isoformat() if assessment.deadline_at else None,
        expires_at=assessment.expires_at.isoformat() if assessment.expires_at else None,
        branding_name=assessment.branding_name,
        branding_logo_url=assessment.branding_logo_url,
        module_plan=module_plan,
        module_count=len(module_plan),
        current_module_index=current_module_index,
        current_module_type=current_module.get("module_type") if current_module else None,
        current_module_title=current_module.get("title") if current_module else None,
        current_module_preview=current_module_preview,
        active_interview_id=active_interview_id,
        can_start_current_module=can_start_current_assessment_module_via_interview(
            assessment,
            has_active_interview=has_active_interview,
        ),
    )


@router.post("/invite/{token}/start", response_model=StartAssessmentResponse)
async def start_employee_assessment(
    token: str,
    body: StartAssessmentRequest,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated candidate starts their employee assessment via invite link."""
    user, candidate = user_and_candidate
    from app.services.assessment_invite_service import get_assessment_by_token as _get
    assessment = await _get(db, token)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    try:
        assessment_obj, interview = await link_interview_to_assessment(
            db,
            token=token,
            candidate=candidate,
            candidate_email=user.email,
            target_role=assessment.target_role,
            language=body.language,
        )
    except GroqAuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service authentication failed. Check GROQ_API_KEY configuration.",
        ) from None
    return StartAssessmentResponse(
        interview_id=str(interview.id),
        assessment_id=str(assessment_obj.id),
    )
