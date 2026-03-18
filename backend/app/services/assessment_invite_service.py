"""
Company assessment invite service.

Handles creation, listing, and linking of company-initiated employee assessments.
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.company_assessment import CompanyAssessment
from app.models.interview import Interview
from app.models.report import AssessmentReport


async def create_assessment(
    db: AsyncSession,
    company_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    employee_email: str,
    employee_name: str,
    target_role: str,
) -> CompanyAssessment:
    assessment = CompanyAssessment(
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        employee_email=employee_email,
        employee_name=employee_name,
        target_role=target_role,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    return assessment


async def get_assessment_by_token(
    db: AsyncSession, token: str
) -> CompanyAssessment | None:
    return await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.invite_token == token)
    )


async def list_company_assessments(
    db: AsyncSession, company_id: uuid.UUID
) -> list[dict]:
    result = await db.execute(
        select(CompanyAssessment)
        .where(CompanyAssessment.company_id == company_id)
        .order_by(CompanyAssessment.created_at.desc())
    )
    assessments = list(result.scalars().all())

    rows = []
    for a in assessments:
        report_id = None
        if a.interview_id:
            report = await db.scalar(
                select(AssessmentReport).where(AssessmentReport.interview_id == a.interview_id)
            )
            if report:
                report_id = str(report.id)

        rows.append({
            "id": str(a.id),
            "employee_email": a.employee_email,
            "employee_name": a.employee_name,
            "target_role": a.target_role,
            "status": a.status,
            "invite_token": a.invite_token,
            "interview_id": str(a.interview_id) if a.interview_id else None,
            "report_id": report_id,
            "created_at": a.created_at.isoformat(),
        })
    return rows


async def link_interview_to_assessment(
    db: AsyncSession,
    token: str,
    candidate: Candidate,
    candidate_email: str,
    target_role: str,
    language: str,
) -> tuple[CompanyAssessment, Interview]:
    """
    Called when an employee starts an interview via invite link.
    Creates the interview and links it to the assessment.
    """
    from app.services.interview_service import start_interview

    assessment = await get_assessment_by_token(db, token)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if assessment.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This assessment has already been completed")
    if assessment.status == "in_progress" and assessment.interview_id:
        # Return existing interview
        interview = await db.scalar(
            select(Interview).where(Interview.id == assessment.interview_id)
        )
        if interview:
            return assessment, interview

    # Verify role matches
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
        template_id=None,
        language=language,
    )
    interview = await db.scalar(select(Interview).where(Interview.id == start_response.interview_id))
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Interview was created but could not be loaded",
        )

    # Link
    interview.company_assessment_id = assessment.id
    assessment.interview_id = interview.id
    assessment.status = "in_progress"
    await db.commit()
    await db.refresh(assessment)
    await db.refresh(interview)

    return assessment, interview


async def sync_assessment_status(
    db: AsyncSession, interview_id: uuid.UUID
) -> None:
    """Called after interview completes — updates assessment status to completed."""
    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.interview_id == interview_id)
    )
    if assessment and assessment.status == "in_progress":
        assessment.status = "completed"
        await db.commit()


async def delete_assessment(
    db: AsyncSession, assessment_id: uuid.UUID, company_id: uuid.UUID
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
