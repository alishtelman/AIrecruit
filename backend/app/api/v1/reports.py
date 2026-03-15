import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.report import AssessmentReport
from app.models.user import User
from app.schemas.report import AssessmentReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{report_id}", response_model=AssessmentReportResponse)
async def get_report(
    report_id: uuid.UUID,
    user_and_candidate: tuple[User, Candidate] = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    _, candidate = user_and_candidate
    report = await db.scalar(
        select(AssessmentReport).where(
            AssessmentReport.id == report_id,
            AssessmentReport.candidate_id == candidate.id,
        )
    )
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report
