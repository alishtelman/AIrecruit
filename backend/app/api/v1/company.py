import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_company_admin, get_db
from app.models.user import User
from app.schemas.company import CandidateDetailResponse, CandidateListItemResponse
from app.services.company_service import get_candidate_detail, list_verified_candidates

router = APIRouter(prefix="/company", tags=["company"])


@router.get("/candidates", response_model=list[CandidateListItemResponse])
async def get_candidates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_company_admin),
):
    return await list_verified_candidates(db)


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailResponse)
async def get_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_company_admin),
):
    result = await get_candidate_detail(db, candidate_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return result
