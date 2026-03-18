import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, field_validator
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import (
    Candidate,
    PROFILE_VISIBILITIES,
    PROFILE_VISIBILITY_DIRECT_LINK,
    PROFILE_VISIBILITY_MARKETPLACE,
    PROFILE_VISIBILITY_REQUEST_ONLY,
)
from app.models.candidate_access_request import (
    ACCESS_REQUEST_APPROVED,
    ACCESS_REQUEST_DENIED,
    ACCESS_REQUEST_PENDING,
)
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.resume import Resume
from app.models.user import User  # noqa: F401 (used by type hints in deps)
from app.schemas.resume import ResumeUploadResponse
from app.services.candidate_access_service import (
    list_candidate_access_requests,
    respond_to_candidate_access_request,
)
from app.services.collaboration_service import log_candidate_activity
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


class CandidatePrivacyResponse(BaseModel):
    visibility: str
    share_token: str | None = None


class CandidateAccessRequestResponse(BaseModel):
    request_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    requested_by_user_id: uuid.UUID | None = None
    requested_by_email: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class CandidatePrivacyUpdateRequest(BaseModel):
    visibility: str

    @field_validator("visibility")
    @classmethod
    def visibility_must_be_supported(cls, v: str) -> str:
        if v not in PROFILE_VISIBILITIES:
            raise ValueError("Unsupported visibility value.")
        return v


class SharedCandidateReportResponse(BaseModel):
    report_id: str
    interview_id: str | None
    target_role: str
    overall_score: float | None
    hiring_recommendation: str
    interview_summary: str | None
    completed_at: datetime | None
    strengths: list[str]
    recommendations: list[str]
    skill_tags: list[dict] | None = None


class SharedCandidateProfileResponse(BaseModel):
    candidate_id: str
    full_name: str
    visibility: str
    requires_approval: bool = False
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    reports: list[SharedCandidateReportResponse]


async def _ensure_share_token(db: AsyncSession, candidate: Candidate) -> str:
    if candidate.public_share_token:
        return candidate.public_share_token

    while True:
        token = secrets.token_urlsafe(24)
        existing = await db.scalar(
            select(Candidate).where(Candidate.public_share_token == token)
        )
        if existing is None:
            candidate.public_share_token = token
            return token


def _build_privacy_response(candidate: Candidate) -> CandidatePrivacyResponse:
    share_token = (
        candidate.public_share_token
        if candidate.profile_visibility in {PROFILE_VISIBILITY_DIRECT_LINK, PROFILE_VISIBILITY_REQUEST_ONLY}
        else None
    )
    return CandidatePrivacyResponse(
        visibility=candidate.profile_visibility,
        share_token=share_token,
    )


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
            Candidate.profile_visibility == PROFILE_VISIBILITY_MARKETPLACE,
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


@router.get("/privacy", response_model=CandidatePrivacyResponse)
async def get_privacy(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
):
    _, candidate = user_and_candidate
    return _build_privacy_response(candidate)


@router.patch("/privacy", response_model=CandidatePrivacyResponse)
async def update_privacy(
    body: CandidatePrivacyUpdateRequest,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    candidate.profile_visibility = body.visibility
    if body.visibility in {PROFILE_VISIBILITY_DIRECT_LINK, PROFILE_VISIBILITY_REQUEST_ONLY}:
        await _ensure_share_token(db, candidate)
    await db.commit()
    await db.refresh(candidate)
    return _build_privacy_response(candidate)


@router.get("/access-requests", response_model=list[CandidateAccessRequestResponse])
async def get_candidate_access_requests(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    requests = await list_candidate_access_requests(db, candidate.id)
    return [
        CandidateAccessRequestResponse(
            request_id=request.id,
            company_id=request.company_id,
            company_name=request.company.name if request.company else "Unknown company",
            requested_by_user_id=request.requested_by_user_id,
            requested_by_email=request.requested_by.email if request.requested_by else None,
            status=request.status,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )
        for request in requests
    ]


@router.post("/access-requests/{request_id}/approve", response_model=CandidateAccessRequestResponse)
async def approve_candidate_access_request(
    request_id: uuid.UUID,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    request = await respond_to_candidate_access_request(
        db,
        candidate_id=candidate.id,
        request_id=request_id,
        approve=True,
    )
    await log_candidate_activity(
        db,
        company_id=request.company_id,
        candidate_id=candidate.id,
        actor_user_id=None,
        activity_type="access_approved",
        summary="Candidate approved workspace access",
        metadata={"access_request_id": str(request.id)},
    )
    return CandidateAccessRequestResponse(
        request_id=request.id,
        company_id=request.company_id,
        company_name=request.company.name if request.company else "Unknown company",
        requested_by_user_id=request.requested_by_user_id,
        requested_by_email=request.requested_by.email if request.requested_by else None,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


@router.post("/access-requests/{request_id}/deny", response_model=CandidateAccessRequestResponse)
async def deny_candidate_access_request(
    request_id: uuid.UUID,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    request = await respond_to_candidate_access_request(
        db,
        candidate_id=candidate.id,
        request_id=request_id,
        approve=False,
    )
    await log_candidate_activity(
        db,
        company_id=request.company_id,
        candidate_id=candidate.id,
        actor_user_id=None,
        activity_type="access_denied",
        summary="Candidate denied workspace access",
        metadata={"access_request_id": str(request.id)},
    )
    return CandidateAccessRequestResponse(
        request_id=request.id,
        company_id=request.company_id,
        company_name=request.company.name if request.company else "Unknown company",
        requested_by_user_id=request.requested_by_user_id,
        requested_by_email=request.requested_by.email if request.requested_by else None,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


@router.get("/share/{share_token}", response_model=SharedCandidateProfileResponse)
async def get_shared_candidate_profile(
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    candidate = await db.scalar(
        select(Candidate).where(Candidate.public_share_token == share_token)
    )
    if not candidate or candidate.profile_visibility not in {
        PROFILE_VISIBILITY_MARKETPLACE,
        PROFILE_VISIBILITY_DIRECT_LINK,
        PROFILE_VISIBILITY_REQUEST_ONLY,
    }:
        raise HTTPException(status_code=404, detail="Shared candidate profile not found.")

    reports: list[SharedCandidateReportResponse] = []
    if candidate.profile_visibility != PROFILE_VISIBILITY_REQUEST_ONLY:
        result = await db.execute(
            select(AssessmentReport, Interview)
            .join(Interview, AssessmentReport.interview_id == Interview.id)
            .where(
                AssessmentReport.candidate_id == candidate.id,
                Interview.company_assessment_id.is_(None),
            )
            .order_by(desc(AssessmentReport.created_at))
        )
        reports = [
            SharedCandidateReportResponse(
                report_id=str(report.id),
                interview_id=str(interview.id) if interview else None,
                target_role=interview.target_role,
                overall_score=report.overall_score,
                hiring_recommendation=report.hiring_recommendation,
                interview_summary=report.interview_summary,
                completed_at=interview.completed_at,
                strengths=report.strengths,
                recommendations=report.recommendations,
                skill_tags=report.skill_tags,
            )
            for report, interview in result.all()
        ]

    return SharedCandidateProfileResponse(
        candidate_id=str(candidate.id),
        full_name=candidate.full_name,
        visibility=candidate.profile_visibility,
        requires_approval=candidate.profile_visibility == PROFILE_VISIBILITY_REQUEST_ONLY,
        salary_min=candidate.salary_min,
        salary_max=candidate.salary_max,
        salary_currency=candidate.salary_currency,
        reports=reports,
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
