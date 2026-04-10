"""
Interview endpoints.

Design decision — interview_id in PATH (nested routes):
  POST /interviews/start            → creates new interview, no ID needed
  POST /interviews/{id}/message     → ID in path, action on a specific resource
  POST /interviews/{id}/finish      → ID in path, action on a specific resource
  GET  /interviews/{id}             → ID in path, standard resource retrieval

Why path over body:
  - RESTful: the interview is the resource, actions operate on it
  - No FastAPI routing conflict (literal "start" resolves before {id})
  - Easier to log, cache, and trace requests by resource ID
  - Client code is simpler (URL carries context, not payload)
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from groq import AuthenticationError as GroqAuthenticationError
from groq import RateLimitError as GroqRateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.user import User
from app.schemas.interview import (
    BehavioralSignalsRequest,
    CodingTaskArtifactRequest,
    CodingTaskArtifactResponse,
    FinishInterviewResponse,
    InterviewDetailResponse,
    InterviewListItemResponse,
    InterviewReportStatusResponse,
    SendMessageRequest,
    SendMessageResponse,
    StartInterviewRequest,
    StartInterviewResponse,
)
from app.schemas.template import TemplateResponse
from app.services.interview_service import (
    InterviewAlreadyFinishedError,
    InterviewNotActiveError,
    InterviewNotFoundError,
    MaxQuestionsNotReachedError,
    MaxQuestionsReachedError,
    NoActiveResumeError,
    CodingTaskArtifactUnavailableError,
    ReportRetryNotAllowedError,
    add_candidate_message,
    finish_interview,
    get_coding_task_artifact,
    get_interview_detail,
    get_interview_report_status,
    list_interviews,
    retry_interview_report_generation,
    save_behavioral_signals,
    save_coding_task_artifact,
    save_interview_recording,
    start_interview,
)
from app.services.template_service import list_public_templates

router = APIRouter(prefix="/interviews", tags=["interviews"])


def _ai_auth_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="AI service authentication failed. Check GROQ_API_KEY configuration.",
    )


def _candidate(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
) -> Candidate:
    _, candidate = user_and_candidate
    return candidate


@router.get(
    "/templates/public",
    response_model=list[TemplateResponse],
    summary="List all public interview templates",
)
async def get_public_templates(db: AsyncSession = Depends(get_db)):
    templates = await list_public_templates(db)
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


@router.get(
    "/",
    response_model=list[InterviewListItemResponse],
    summary="List all interviews for the current candidate",
)
async def list_all(
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    return await list_interviews(db, candidate)


@router.post(
    "/start",
    response_model=StartInterviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new interview (requires active resume)",
)
async def start(
    body: StartInterviewRequest,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await start_interview(db, candidate, body.target_role, body.template_id, body.language)
    except NoActiveResumeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No active resume found. Please upload a resume before starting an interview.",
        )
    except GroqAuthenticationError:
        raise _ai_auth_http_error()
    except GroqRateLimitError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service rate limit reached. Please wait a few minutes and try again.",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )


@router.post(
    "/{interview_id}/message",
    response_model=SendMessageResponse,
    summary="Send a candidate answer and receive the next question",
)
async def send_message(
    interview_id: uuid.UUID,
    body: SendMessageRequest,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await add_candidate_message(db, candidate, interview_id, body.message)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    except InterviewAlreadyFinishedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview is already finished. Call GET /interviews/{id} to review results.",
        )
    except MaxQuestionsReachedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="All questions answered. Call POST /interviews/{id}/finish to generate your report.",
        )
    except InterviewNotActiveError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview is not active.",
        )
    except GroqAuthenticationError:
        raise _ai_auth_http_error()
    except GroqRateLimitError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service rate limit reached. Please wait a few minutes and try again.",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )


@router.post(
    "/{interview_id}/finish",
    response_model=FinishInterviewResponse,
    summary="Finish interview and generate assessment report",
)
async def finish(
    interview_id: uuid.UUID,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await finish_interview(db, candidate, interview_id)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    except InterviewAlreadyFinishedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report already generated for this interview.",
        )
    except InterviewNotActiveError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview is not active.",
        )
    except GroqAuthenticationError:
        raise _ai_auth_http_error()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except MaxQuestionsNotReachedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot finish yet. Please answer all questions first.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation failed. Interview marked as failed.",
        )


@router.post(
    "/{interview_id}/signals",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Submit behavioral signals captured during the interview",
)
async def submit_signals(
    interview_id: uuid.UUID,
    body: BehavioralSignalsRequest,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        await save_behavioral_signals(db, candidate.id, interview_id, body.model_dump())
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")


@router.post(
    "/{interview_id}/recording",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upload interview recording",
)
async def upload_recording(
    interview_id: uuid.UUID,
    file: UploadFile = File(...),
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        await save_interview_recording(db, candidate.id, interview_id, file)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")


@router.get(
    "/{interview_id}/coding-artifact",
    response_model=CodingTaskArtifactResponse,
    summary="Get the saved code artifact for a coding task interview",
)
async def get_saved_coding_artifact(
    interview_id: uuid.UUID,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_coding_task_artifact(db, candidate, interview_id)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    except CodingTaskArtifactUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.put(
    "/{interview_id}/coding-artifact",
    response_model=CodingTaskArtifactResponse,
    summary="Save the code artifact for a coding task interview",
)
async def save_coding_artifact(
    interview_id: uuid.UUID,
    body: CodingTaskArtifactRequest,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await save_coding_task_artifact(
            db,
            candidate,
            interview_id,
            code=body.code,
            language=body.language,
        )
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    except InterviewNotActiveError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview is not active.",
        )
    except CodingTaskArtifactUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/{interview_id}",
    response_model=InterviewDetailResponse,
    summary="Get interview details, messages, and report status",
)
async def get_detail(
    interview_id: uuid.UUID,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_interview_detail(db, candidate, interview_id)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")


@router.get(
    "/{interview_id}/report-status",
    response_model=InterviewReportStatusResponse,
    summary="Get asynchronous report generation status for an interview",
)
async def get_report_status(
    interview_id: uuid.UUID,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_interview_report_status(db, candidate, interview_id)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")


@router.post(
    "/{interview_id}/report-retry",
    response_model=InterviewReportStatusResponse,
    summary="Retry report generation for a completed or failed interview",
)
async def retry_report(
    interview_id: uuid.UUID,
    candidate: Candidate = Depends(_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await retry_interview_report_generation(db, candidate, interview_id)
    except InterviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    except ReportRetryNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
