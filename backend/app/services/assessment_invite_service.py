"""
Company assessment invite service.

Handles creation, listing, and linking of company-owned private assessment campaigns.
"""
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.company_assessment import CompanyAssessment
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.template import InterviewTemplate

_ACTIVE_INVITE_STATUSES = {"pending", "opened"}


def _is_past_due(assessment: CompanyAssessment, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if assessment.expires_at and now >= assessment.expires_at:
        return True
    if assessment.deadline_at and now >= assessment.deadline_at:
        return True
    return False


async def _refresh_assessment_status(
    db: AsyncSession,
    assessment: CompanyAssessment,
    *,
    now: datetime | None = None,
) -> CompanyAssessment:
    if assessment.status in _ACTIVE_INVITE_STATUSES and _is_past_due(assessment, now):
        assessment.status = "expired"
        await db.commit()
    return assessment


async def _serialize_assessment_rows(
    db: AsyncSession,
    assessments: list[CompanyAssessment],
) -> list[dict]:
    assessments = [await _refresh_assessment_status(db, assessment) for assessment in assessments]
    interview_ids = [assessment.interview_id for assessment in assessments if assessment.interview_id]
    report_map: dict[uuid.UUID, str] = {}
    if interview_ids:
        reports = await db.execute(
            select(AssessmentReport).where(AssessmentReport.interview_id.in_(interview_ids))
        )
        for report in reports.scalars().all():
            report_map[report.interview_id] = str(report.id)

    rows: list[dict] = []
    for assessment in assessments:
        rows.append(
            {
                "id": str(assessment.id),
                "employee_email": assessment.employee_email,
                "employee_name": assessment.employee_name,
                "assessment_type": assessment.assessment_type,
                "target_role": assessment.target_role,
                "template_id": str(assessment.template_id) if assessment.template_id else None,
                "template_name": assessment.template.name if assessment.template else None,
                "status": assessment.status,
                "invite_token": assessment.invite_token,
                "interview_id": str(assessment.interview_id) if assessment.interview_id else None,
                "report_id": report_map.get(assessment.interview_id) if assessment.interview_id else None,
                "deadline_at": assessment.deadline_at.isoformat() if assessment.deadline_at else None,
                "expires_at": assessment.expires_at.isoformat() if assessment.expires_at else None,
                "opened_at": assessment.opened_at.isoformat() if assessment.opened_at else None,
                "completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
                "branding_name": assessment.branding_name,
                "branding_logo_url": assessment.branding_logo_url,
                "created_at": assessment.created_at.isoformat(),
            }
        )
    return rows


async def create_assessment(
    db: AsyncSession,
    company_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    employee_email: str,
    employee_name: str,
    target_role: str,
    *,
    assessment_type: str = "employee_internal",
    template_id: uuid.UUID | None = None,
    deadline_at: datetime | None = None,
    expires_at: datetime | None = None,
    branding_name: str | None = None,
    branding_logo_url: str | None = None,
) -> CompanyAssessment:
    if assessment_type not in {"employee_internal", "candidate_external"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid assessment type")
    if deadline_at and expires_at and deadline_at > expires_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="deadline_at must be earlier than or equal to expires_at",
        )

    template: InterviewTemplate | None = None
    if template_id:
        template = await db.scalar(
            select(InterviewTemplate).where(InterviewTemplate.id == template_id)
        )
        if not template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        if template.company_id != company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your template")
        if template.target_role != target_role:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Template role does not match assessment target_role",
            )

    assessment = CompanyAssessment(
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        employee_email=employee_email.strip().lower(),
        employee_name=employee_name.strip(),
        assessment_type=assessment_type,
        target_role=target_role,
        template_id=template_id,
        deadline_at=deadline_at,
        expires_at=expires_at,
        branding_name=branding_name.strip() if branding_name else None,
        branding_logo_url=branding_logo_url.strip() if branding_logo_url else None,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    if template is not None:
        assessment.template = template
    return assessment


async def get_assessment_by_token(
    db: AsyncSession,
    token: str,
) -> CompanyAssessment | None:
    assessment = await db.scalar(
        select(CompanyAssessment)
        .options(
            selectinload(CompanyAssessment.company),
            selectinload(CompanyAssessment.template),
        )
        .where(CompanyAssessment.invite_token == token)
    )
    if assessment:
        await _refresh_assessment_status(db, assessment)
    return assessment


async def get_assessment_for_invite_view(
    db: AsyncSession,
    token: str,
) -> CompanyAssessment | None:
    assessment = await get_assessment_by_token(db, token)
    if not assessment:
        return None
    if assessment.status == "pending":
        assessment.status = "opened"
        assessment.opened_at = assessment.opened_at or datetime.utcnow()
        await db.commit()
    return assessment


async def list_company_assessments(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> list[dict]:
    result = await db.execute(
        select(CompanyAssessment)
        .options(selectinload(CompanyAssessment.template))
        .where(CompanyAssessment.company_id == company_id)
        .order_by(CompanyAssessment.created_at.desc())
    )
    assessments = list(result.scalars().all())
    return await _serialize_assessment_rows(db, assessments)


async def link_interview_to_assessment(
    db: AsyncSession,
    token: str,
    candidate: Candidate,
    candidate_email: str,
    target_role: str,
    language: str,
) -> tuple[CompanyAssessment, Interview]:
    """
    Called when an invitee starts an interview via invite link.
    Creates the interview and links it to the assessment.
    """
    from app.services.interview_service import start_interview

    assessment = await get_assessment_by_token(db, token)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if assessment.status == "expired":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This assessment invite has expired")
    if assessment.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This assessment has already been completed")
    if assessment.status == "in_progress" and assessment.interview_id:
        interview = await db.scalar(
            select(Interview).where(Interview.id == assessment.interview_id)
        )
        if interview:
            return assessment, interview

    if assessment.target_role != target_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This invite is for role '{assessment.target_role}', not '{target_role}'",
        )

    if candidate_email.strip().lower() != assessment.employee_email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This assessment invite is assigned to a different email address",
        )

    start_response = await start_interview(
        db,
        candidate=candidate,
        target_role=target_role,
        template_id=assessment.template_id,
        language=language,
    )
    interview = await db.scalar(select(Interview).where(Interview.id == start_response.interview_id))
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Interview was created but could not be loaded",
        )

    interview.company_assessment_id = assessment.id
    assessment.interview_id = interview.id
    assessment.status = "in_progress"
    assessment.opened_at = assessment.opened_at or datetime.utcnow()
    await db.commit()
    await db.refresh(assessment)
    await db.refresh(interview)

    return assessment, interview


async def sync_assessment_status(
    db: AsyncSession,
    interview_id: uuid.UUID,
) -> None:
    """Called after interview completes — updates assessment status to completed."""
    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.interview_id == interview_id)
    )
    if assessment and assessment.status == "in_progress":
        assessment.status = "completed"
        assessment.completed_at = datetime.utcnow()
        await db.commit()


async def delete_assessment(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    company_id: uuid.UUID,
) -> None:
    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.id == assessment_id)
    )
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    if assessment.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your assessment")
    await db.delete(assessment)
    await db.commit()
