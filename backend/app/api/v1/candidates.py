from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.resume import Resume
from app.models.user import User
from app.schemas.resume import ResumeUploadResponse
from app.services.resume_service import upload_resume

router = APIRouter(prefix="/candidate", tags=["candidate"])


class CandidateStatsResponse(BaseModel):
    has_resume: bool
    interview_count: int
    completed_count: int
    latest_report_id: str | None


class ActiveResumeResponse(BaseModel):
    resume_id: str
    file_name: str
    file_size: int
    uploaded_at: datetime


@router.get("/stats", response_model=CandidateStatsResponse)
async def get_stats(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate

    has_resume = await db.scalar(
        select(func.count()).where(
            Resume.candidate_id == candidate.id,
            Resume.is_active.is_(True),
        )
    ) > 0

    interview_count = await db.scalar(
        select(func.count()).where(Interview.candidate_id == candidate.id)
    )

    completed_count = await db.scalar(
        select(func.count()).where(
            Interview.candidate_id == candidate.id,
            Interview.status == "report_generated",
        )
    )

    latest_report = await db.scalar(
        select(AssessmentReport)
        .where(AssessmentReport.candidate_id == candidate.id)
        .order_by(AssessmentReport.created_at.desc())
    )

    return CandidateStatsResponse(
        has_resume=has_resume,
        interview_count=interview_count or 0,
        completed_count=completed_count or 0,
        latest_report_id=str(latest_report.id) if latest_report else None,
    )


@router.get("/resume", response_model=ActiveResumeResponse | None)
async def get_active_resume(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    resume = await db.scalar(
        select(Resume)
        .where(Resume.candidate_id == candidate.id, Resume.is_active.is_(True))
        .order_by(Resume.created_at.desc())
    )
    if not resume:
        return None
    return ActiveResumeResponse(
        resume_id=str(resume.id),
        file_name=resume.file_name,
        file_size=resume.file_size,
        uploaded_at=resume.created_at,
    )


@router.post(
    "/resume/upload",
    response_model=ResumeUploadResponse,
    summary="Upload resume (PDF or DOCX, max 10 MB)",
)
async def upload_candidate_resume(
    file: UploadFile = File(...),
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    return await upload_resume(db, file, candidate)
