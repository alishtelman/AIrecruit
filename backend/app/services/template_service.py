import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import InterviewTemplate


async def create_template(
    db: AsyncSession,
    company_id: uuid.UUID,
    name: str,
    target_role: str,
    questions: list[str],
    description: str | None,
    is_public: bool,
) -> InterviewTemplate:
    template = InterviewTemplate(
        company_id=company_id,
        name=name,
        target_role=target_role,
        questions=questions,
        description=description,
        is_public=is_public,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def list_company_templates(
    db: AsyncSession, company_id: uuid.UUID
) -> list[InterviewTemplate]:
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.company_id == company_id)
        .order_by(InterviewTemplate.created_at.desc())
    )
    return list(result.scalars().all())


async def list_public_templates(db: AsyncSession) -> list[InterviewTemplate]:
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.is_public.is_(True))
        .order_by(InterviewTemplate.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_template(
    db: AsyncSession, template_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    template = await db.scalar(
        select(InterviewTemplate).where(InterviewTemplate.id == template_id)
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your template")
    await db.delete(template)
    await db.commit()


async def get_template(
    db: AsyncSession, template_id: uuid.UUID
) -> InterviewTemplate | None:
    return await db.scalar(
        select(InterviewTemplate).where(InterviewTemplate.id == template_id)
    )
