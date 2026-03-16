"""
Employee assessment invite endpoints.

GET  /api/v1/employee/invite/{token}        — public, returns invite info
POST /api/v1/employee/invite/{token}/start  — authenticated candidate, starts interview
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate, get_db
from app.models.candidate import Candidate
from app.models.user import User
from app.services.assessment_invite_service import (
    get_assessment_by_token,
    link_interview_to_assessment,
)

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
    employee_name: str
    employee_email: str
    target_role: str
    role_label: str
    status: str
    company_name: str


class StartAssessmentRequest(BaseModel):
    language: str = "ru"


class StartAssessmentResponse(BaseModel):
    interview_id: str
    assessment_id: str


@router.get("/invite/{token}", response_model=InviteInfoResponse)
async def get_invite_info(token: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns invite details so employee can see who invited them."""
    from fastapi import HTTPException, status
    assessment = await get_assessment_by_token(db, token)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or expired")

    return InviteInfoResponse(
        employee_name=assessment.employee_name,
        employee_email=assessment.employee_email,
        target_role=assessment.target_role,
        role_label=_ROLE_LABELS.get(assessment.target_role, assessment.target_role),
        status=assessment.status,
        company_name=assessment.company.name,
    )


@router.post("/invite/{token}/start", response_model=StartAssessmentResponse)
async def start_employee_assessment(
    token: str,
    body: StartAssessmentRequest,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated candidate starts their employee assessment via invite link."""
    _, candidate = user_and_candidate
    from app.services.assessment_invite_service import get_assessment_by_token as _get
    assessment = await _get(db, token)
    if not assessment:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    assessment_obj, interview = await link_interview_to_assessment(
        db,
        token=token,
        candidate_id=candidate.id,
        target_role=assessment.target_role,
        language=body.language,
    )
    return StartAssessmentResponse(
        interview_id=str(interview.id),
        assessment_id=str(assessment_obj.id),
    )
