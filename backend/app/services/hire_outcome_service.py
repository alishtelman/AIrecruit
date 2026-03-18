"""Hire outcome service — record hiring decisions per candidate."""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hire_outcome import HireOutcome
from app.services.candidate_access_service import ensure_company_candidate_workspace_access
from app.services.collaboration_service import log_candidate_activity


VALID_OUTCOMES = {"hired", "rejected", "interviewing", "no_show"}


async def set_hire_outcome(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
    outcome: str,
    notes: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> HireOutcome:
    await ensure_company_candidate_workspace_access(db, company_id, candidate_id)

    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Invalid outcome '{outcome}'. Must be one of {VALID_OUTCOMES}")

    existing = await db.scalar(
        select(HireOutcome).where(
            HireOutcome.company_id == company_id,
            HireOutcome.candidate_id == candidate_id,
        )
    )
    if existing:
        previous_outcome = existing.outcome
        existing.outcome = outcome
        existing.notes = notes
        existing.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing)
        await log_candidate_activity(
            db,
            company_id=company_id,
            candidate_id=candidate_id,
            actor_user_id=actor_user_id,
            activity_type="outcome_updated",
            summary=f"Updated hiring outcome from '{previous_outcome}' to '{outcome}'",
            metadata={"outcome": outcome, "previous_outcome": previous_outcome, "notes": notes},
        )
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
    await log_candidate_activity(
        db,
        company_id=company_id,
        candidate_id=candidate_id,
        actor_user_id=actor_user_id,
        activity_type="outcome_set",
        summary=f"Set hiring outcome to '{outcome}'",
        metadata={"outcome": outcome, "notes": notes},
    )
    return record


async def get_hire_outcome(
    db: AsyncSession,
    company_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> HireOutcome | None:
    await ensure_company_candidate_workspace_access(db, company_id, candidate_id)
    return await db.scalar(
        select(HireOutcome).where(
            HireOutcome.company_id == company_id,
            HireOutcome.candidate_id == candidate_id,
        )
    )
