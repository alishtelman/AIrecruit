"""Hire outcome service — record hiring decisions per candidate."""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hire_outcome import HireOutcome


VALID_OUTCOMES = {"hired", "rejected", "interviewing", "no_show"}


async def set_hire_outcome(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
    outcome: str,
    notes: str | None = None,
) -> HireOutcome:
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Invalid outcome '{outcome}'. Must be one of {VALID_OUTCOMES}")

    existing = await db.scalar(
        select(HireOutcome).where(
            HireOutcome.company_id == company_id,
            HireOutcome.candidate_id == candidate_id,
        )
    )
    if existing:
        existing.outcome = outcome
        existing.notes = notes
        existing.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing)
        return existing

    record = HireOutcome(
        id=uuid.uuid4(),
        company_id=company_id,
        candidate_id=candidate_id,
        outcome=outcome,
        notes=notes,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_hire_outcome(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> HireOutcome | None:
    return await db.scalar(
        select(HireOutcome).where(
            HireOutcome.company_id == company_id,
            HireOutcome.candidate_id == candidate_id,
        )
    )
