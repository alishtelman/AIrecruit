from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.resume import Resume
from app.models.user import User  # noqa: F401 (used by type hints in deps)
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


class ResumeTextResponse(BaseModel):
    resume_id: str
    file_name: str
    raw_text: str


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


@router.get("/resume/text", response_model=ResumeTextResponse)
async def get_resume_text(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    _, candidate = user_and_candidate
    resume = await db.scalar(
        select(Resume)
        .where(Resume.candidate_id == candidate.id, Resume.is_active.is_(True))
        .order_by(Resume.created_at.desc())
    )
    if not resume:
        raise HTTPException(status_code=404, detail="No active resume found.")
    return ResumeTextResponse(
        resume_id=str(resume.id),
        file_name=resume.file_name,
        raw_text=resume.raw_text or "",
    )


class SalaryUpdateRequest(BaseModel):
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str = "USD"


class SalaryResponse(BaseModel):
    salary_min: int | None
    salary_max: int | None
    salary_currency: str


class BenchmarkBucket(BaseModel):
    score_range: str
    median_min: float | None
    median_max: float | None
    count: int


class SalaryBenchmarkResponse(BaseModel):
    role: str
    buckets: list[BenchmarkBucket]


@router.patch("/salary", response_model=SalaryResponse)
async def update_salary(
    body: SalaryUpdateRequest,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    candidate.salary_min = body.salary_min
    candidate.salary_max = body.salary_max
    candidate.salary_currency = body.currency
    await db.commit()
    await db.refresh(candidate)
    return SalaryResponse(
        salary_min=candidate.salary_min,
        salary_max=candidate.salary_max,
        salary_currency=candidate.salary_currency,
    )


@router.get("/salary", response_model=SalaryResponse)
async def get_salary(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    return SalaryResponse(
        salary_min=candidate.salary_min,
        salary_max=candidate.salary_max,
        salary_currency=candidate.salary_currency,
    )


@router.get("/salary/benchmark", response_model=SalaryBenchmarkResponse)
async def salary_benchmark(
    role: str,
    db: AsyncSession = Depends(get_db),
):
    """Return median salary expectations by score bucket for a given role."""
    # Get all candidates who set salary AND have a report for this role
    result = await db.execute(
        select(Candidate, AssessmentReport)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .join(Candidate, AssessmentReport.candidate_id == Candidate.id)
        .where(
            Interview.target_role == role,
            Candidate.salary_min.isnot(None),
        )
    )
    rows = result.all()

    buckets_data: dict[str, list[tuple[int, int]]] = {
        "0-4": [], "5-6": [], "7-8": [], "9-10": [],
    }

    def _bucket(score: float | None) -> str:
        if score is None:
            return "0-4"
        if score <= 4:
            return "0-4"
        if score <= 6:
            return "5-6"
        if score <= 8:
            return "7-8"
        return "9-10"

    for candidate, report in rows:
        b = _bucket(report.overall_score)
        if candidate.salary_min is not None:
            buckets_data[b].append((candidate.salary_min, candidate.salary_max or candidate.salary_min))

    def _median(vals: list[float]) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    result_buckets = []
    for score_range, pairs in buckets_data.items():
        mins = [p[0] for p in pairs]
        maxs = [p[1] for p in pairs]
        result_buckets.append(BenchmarkBucket(
            score_range=score_range,
            median_min=_median(mins),
            median_max=_median(maxs),
            count=len(pairs),
        ))

    return SalaryBenchmarkResponse(role=role, buckets=result_buckets)


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
