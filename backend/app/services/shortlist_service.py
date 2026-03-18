import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shortlist import CompanyShortlist, CompanyShortlistCandidate
from app.schemas.company import ShortlistMembershipResponse, ShortlistSummaryResponse
from app.services.candidate_access_service import ensure_company_candidate_workspace_access
from app.services.collaboration_service import log_candidate_activity


async def list_shortlists(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> list[ShortlistSummaryResponse]:
    result = await db.execute(
        select(
            CompanyShortlist,
            func.count(CompanyShortlistCandidate.id),
        )
        .outerjoin(
            CompanyShortlistCandidate,
            CompanyShortlistCandidate.shortlist_id == CompanyShortlist.id,
        )
        .where(CompanyShortlist.company_id == company_id)
        .group_by(CompanyShortlist.id)
        .order_by(CompanyShortlist.created_at.desc())
    )
    return [
        ShortlistSummaryResponse(
            shortlist_id=shortlist.id,
            name=shortlist.name,
            candidate_count=count,
            created_at=shortlist.created_at,
        )
        for shortlist, count in result.all()
    ]


async def create_shortlist(
    db: AsyncSession,
    company_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    name: str,
) -> ShortlistSummaryResponse:
    existing = await db.scalar(
        select(CompanyShortlist).where(
            CompanyShortlist.company_id == company_id,
            CompanyShortlist.name == name,
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shortlist name already exists")

    shortlist = CompanyShortlist(
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        name=name,
    )
    db.add(shortlist)
    await db.commit()
    await db.refresh(shortlist)
    return ShortlistSummaryResponse(
        shortlist_id=shortlist.id,
        name=shortlist.name,
        candidate_count=0,
        created_at=shortlist.created_at,
    )


async def delete_shortlist(
    db: AsyncSession,
    shortlist_id: uuid.UUID,
    company_id: uuid.UUID,
) -> None:
    shortlist = await db.scalar(
        select(CompanyShortlist).where(CompanyShortlist.id == shortlist_id)
    )
    if shortlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shortlist not found")
    if shortlist.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your shortlist")
    await db.delete(shortlist)
    await db.commit()


async def add_candidate_to_shortlist(
    db: AsyncSession,
    shortlist_id: uuid.UUID,
    candidate_id: uuid.UUID,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    shortlist = await db.scalar(
        select(CompanyShortlist).where(CompanyShortlist.id == shortlist_id)
    )
    if shortlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shortlist not found")
    if shortlist.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your shortlist")

    await ensure_company_candidate_workspace_access(db, company_id, candidate_id)

    existing = await db.scalar(
        select(CompanyShortlistCandidate).where(
            CompanyShortlistCandidate.shortlist_id == shortlist_id,
            CompanyShortlistCandidate.candidate_id == candidate_id,
        )
    )
    if existing:
        return

    db.add(CompanyShortlistCandidate(shortlist_id=shortlist_id, candidate_id=candidate_id))
    await db.commit()
    await log_candidate_activity(
        db,
        company_id=company_id,
        candidate_id=candidate_id,
        actor_user_id=actor_user_id,
        activity_type="shortlist_added",
        summary=f"Added candidate to shortlist '{shortlist.name}'",
        metadata={"shortlist_id": str(shortlist_id), "shortlist_name": shortlist.name},
    )


async def remove_candidate_from_shortlist(
    db: AsyncSession,
    shortlist_id: uuid.UUID,
    candidate_id: uuid.UUID,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    shortlist = await db.scalar(
        select(CompanyShortlist).where(CompanyShortlist.id == shortlist_id)
    )
    if shortlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shortlist not found")
    if shortlist.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your shortlist")

    membership = await db.scalar(
        select(CompanyShortlistCandidate).where(
            CompanyShortlistCandidate.shortlist_id == shortlist_id,
            CompanyShortlistCandidate.candidate_id == candidate_id,
        )
    )
    if membership is None:
        return

    await db.delete(membership)
    await db.commit()
    await log_candidate_activity(
        db,
        company_id=company_id,
        candidate_id=candidate_id,
        actor_user_id=actor_user_id,
        activity_type="shortlist_removed",
        summary=f"Removed candidate from shortlist '{shortlist.name}'",
        metadata={"shortlist_id": str(shortlist_id), "shortlist_name": shortlist.name},
    )


async def get_candidate_shortlists_map(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[ShortlistMembershipResponse]]:
    if not candidate_ids:
        return {}

    result = await db.execute(
        select(CompanyShortlistCandidate.candidate_id, CompanyShortlist.id, CompanyShortlist.name)
        .join(CompanyShortlist, CompanyShortlist.id == CompanyShortlistCandidate.shortlist_id)
        .where(
            CompanyShortlist.company_id == company_id,
            CompanyShortlistCandidate.candidate_id.in_(candidate_ids),
        )
        .order_by(CompanyShortlist.name.asc())
    )

    memberships: dict[uuid.UUID, list[ShortlistMembershipResponse]] = {}
    for candidate_id, shortlist_id, shortlist_name in result.all():
        memberships.setdefault(candidate_id, []).append(
            ShortlistMembershipResponse(shortlist_id=shortlist_id, name=shortlist_name)
        )
    return memberships
