from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.user import User
from app.schemas.resume import ResumeUploadResponse
from app.services.resume_service import upload_resume

router = APIRouter(prefix="/candidate", tags=["candidate"])


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
