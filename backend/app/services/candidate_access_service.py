import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import (
    Candidate,
    PROFILE_VISIBILITY_MARKETPLACE,
    PROFILE_VISIBILITY_REQUEST_ONLY,
)
from app.models.candidate_access_request import (
    ACCESS_REQUEST_APPROVED,
    ACCESS_REQUEST_DENIED,
    ACCESS_REQUEST_PENDING,
    CandidateAccessRequest,
)
from app.models.interview import Interview
from app.models.report import AssessmentReport


async def candidate_has_public_workspace_reports(
    db: AsyncSession,
    candidate_id: uuid.UUID,
) -> bool:
    report_exists = await db.scalar(
        select(AssessmentReport.id)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .where(
            AssessmentReport.candidate_id == candidate_id,
            Interview.company_assessment_id.is_(None),
        )
    )
    return report_exists is not None


async def get_candidate_access_request(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> CandidateAccessRequest | None:
    return await db.scalar(
        select(CandidateAccessRequest).where(
            CandidateAccessRequest.company_id == company_id,
            CandidateAccessRequest.candidate_id == candidate_id,
        )
    )


async def has_company_candidate_workspace_access(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate: Candidate,
) -> bool:
    if candidate.profile_visibility == PROFILE_VISIBILITY_MARKETPLACE:
        return True

    request = await get_candidate_access_request(db, company_id, candidate.id)
    return request is not None and request.status == ACCESS_REQUEST_APPROVED


async def ensure_company_candidate_workspace_access(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> Candidate:
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    if not await candidate_has_public_workspace_reports(db, candidate_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    if not await has_company_candidate_workspace_access(db, company_id, candidate):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    return candidate


async def get_candidate_by_share_token(
    db: AsyncSession,
    share_token: str,
) -> Candidate | None:
    return await db.scalar(
        select(Candidate).where(Candidate.public_share_token == share_token)
    )


async def get_share_link_access_status(
    db: AsyncSession,
    share_token: str,
    company_id: uuid.UUID,
) -> tuple[Candidate, CandidateAccessRequest | None, bool]:
    candidate = await get_candidate_by_share_token(db, share_token)
    if not candidate or candidate.profile_visibility != PROFILE_VISIBILITY_REQUEST_ONLY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate share link not found")

    request = await get_candidate_access_request(db, company_id, candidate.id)
    has_workspace_access = bool(request and request.status == ACCESS_REQUEST_APPROVED and await candidate_has_public_workspace_reports(db, candidate.id))
    return candidate, request, has_workspace_access


async def create_share_link_access_request(
    db: AsyncSession,
    share_token: str,
    company_id: uuid.UUID,
    requested_by_user_id: uuid.UUID,
) -> CandidateAccessRequest:
    candidate = await get_candidate_by_share_token(db, share_token)
    if not candidate or candidate.profile_visibility != PROFILE_VISIBILITY_REQUEST_ONLY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate share link not found")

    existing = await get_candidate_access_request(db, company_id, candidate.id)
    if existing is not None:
        if existing.status == ACCESS_REQUEST_APPROVED:
            return existing
        existing.status = ACCESS_REQUEST_PENDING
        existing.requested_by_user_id = requested_by_user_id
        existing.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing)
        return existing

    record = CandidateAccessRequest(
        candidate_id=candidate.id,
        company_id=company_id,
        requested_by_user_id=requested_by_user_id,
        status=ACCESS_REQUEST_PENDING,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def list_candidate_access_requests(
    db: AsyncSession,
    candidate_id: uuid.UUID,
) -> list[CandidateAccessRequest]:
    result = await db.execute(
        select(CandidateAccessRequest)
        .options(
            selectinload(CandidateAccessRequest.company),
            selectinload(CandidateAccessRequest.requested_by),
        )
        .where(CandidateAccessRequest.candidate_id == candidate_id)
        .order_by(desc(CandidateAccessRequest.updated_at))
    )
    return result.scalars().all()


async def respond_to_candidate_access_request(
    db: AsyncSession,
    *,
    candidate_id: uuid.UUID,
    request_id: uuid.UUID,
    approve: bool,
) -> CandidateAccessRequest:
    request = await db.scalar(
        select(CandidateAccessRequest)
        .options(
            selectinload(CandidateAccessRequest.company),
            selectinload(CandidateAccessRequest.requested_by),
        )
        .where(
            CandidateAccessRequest.id == request_id,
            CandidateAccessRequest.candidate_id == candidate_id,
        )
    )
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found")

    request.status = ACCESS_REQUEST_APPROVED if approve else ACCESS_REQUEST_DENIED
    request.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(request)
    await db.refresh(request, attribute_names=["company", "requested_by"])
    return request
