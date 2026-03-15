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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.user import User
from app.schemas.interview import (
    FinishInterviewResponse,
    InterviewDetailResponse,
    SendMessageRequest,
    SendMessageResponse,
    StartInterviewRequest,
    StartInterviewResponse,
)
from app.services.interview_service import (
    InterviewAlreadyFinishedError,
    InterviewNotActiveError,
    InterviewNotFoundError,
    MaxQuestionsNotReachedError,
    MaxQuestionsReachedError,
    NoActiveResumeError,
    add_candidate_message,
    finish_interview,
    get_interview_detail,
    start_interview,
)

router = APIRouter(prefix="/interviews", tags=["interviews"])


def _candidate(
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
) -> Candidate:
    _, candidate = user_and_candidate
    return candidate


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
        return await start_interview(db, candidate, body.target_role)
    except NoActiveResumeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No active resume found. Please upload a resume before starting an interview.",
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
