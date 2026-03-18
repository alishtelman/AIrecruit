import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.collaboration import CompanyCandidateActivity, CompanyCandidateNote
from app.models.user import User
from app.schemas.company import CandidateActivityResponse, CandidateNoteResponse
from app.services.candidate_access_service import ensure_company_candidate_workspace_access


async def ensure_company_candidate_access(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
):
    return await ensure_company_candidate_workspace_access(db, company_id, candidate_id)


async def log_candidate_activity(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    activity_type: str,
    summary: str,
    metadata: dict | None = None,
) -> CompanyCandidateActivity:
    activity = CompanyCandidateActivity(
        company_id=company_id,
        candidate_id=candidate_id,
        actor_user_id=actor_user_id,
        activity_type=activity_type,
        summary=summary,
        payload=metadata,
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    return activity


async def list_candidate_notes(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> list[CandidateNoteResponse]:
    await ensure_company_candidate_access(db, company_id, candidate_id)
    result = await db.execute(
        select(CompanyCandidateNote)
        .options(selectinload(CompanyCandidateNote.author))
        .where(
            CompanyCandidateNote.company_id == company_id,
            CompanyCandidateNote.candidate_id == candidate_id,
        )
        .order_by(desc(CompanyCandidateNote.created_at))
    )
    return [
        CandidateNoteResponse(
            note_id=note.id,
            body=note.body,
            author_user_id=note.author_user_id,
            author_email=note.author.email if note.author else None,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
        for note in result.scalars().all()
    ]


async def create_candidate_note(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
    author_user_id: uuid.UUID,
    body: str,
) -> CandidateNoteResponse:
    await ensure_company_candidate_access(db, company_id, candidate_id)

    note = CompanyCandidateNote(
        company_id=company_id,
        candidate_id=candidate_id,
        author_user_id=author_user_id,
        body=body.strip(),
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    author = await db.scalar(select(User).where(User.id == author_user_id))
    await log_candidate_activity(
        db,
        company_id=company_id,
        candidate_id=candidate_id,
        actor_user_id=author_user_id,
        activity_type="note_added",
        summary="Added a shared candidate note",
        metadata={"preview": body.strip()[:120]},
    )
    return CandidateNoteResponse(
        note_id=note.id,
        body=note.body,
        author_user_id=note.author_user_id,
        author_email=author.email if author else None,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def list_candidate_activity(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> list[CandidateActivityResponse]:
    await ensure_company_candidate_access(db, company_id, candidate_id)

    result = await db.execute(
        select(CompanyCandidateActivity)
        .options(selectinload(CompanyCandidateActivity.actor))
        .where(
            CompanyCandidateActivity.company_id == company_id,
            CompanyCandidateActivity.candidate_id == candidate_id,
        )
        .order_by(desc(CompanyCandidateActivity.created_at))
        .limit(100)
    )

    return [
        CandidateActivityResponse(
            activity_id=activity.id,
            activity_type=activity.activity_type,
            summary=activity.summary,
            actor_user_id=activity.actor_user_id,
            actor_email=activity.actor.email if activity.actor else None,
            metadata=activity.payload,
            created_at=activity.created_at,
        )
        for activity in result.scalars().all()
    ]
