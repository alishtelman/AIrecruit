import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_company, get_current_company_admin, get_db
from app.models.company import Company
from app.models.user import User
from app.schemas.company import CandidateDetailResponse, CandidateListItemResponse
from app.schemas.template import TemplateCreateRequest, TemplateResponse
from app.services.company_service import get_candidate_detail, list_verified_candidates
from app.services.template_service import (
    create_template,
    delete_template,
    list_company_templates,
)

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


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    templates = await list_company_templates(db, company.id)
    return [
        TemplateResponse(
            template_id=t.id,
            company_id=t.company_id,
            name=t.name,
            target_role=t.target_role,
            questions=t.questions,
            description=t.description,
            is_public=t.is_public,
            created_at=t.created_at,
        )
        for t in templates
    ]


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_template(
    body: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    t = await create_template(
        db,
        company_id=company.id,
        name=body.name,
        target_role=body.target_role,
        questions=body.questions,
        description=body.description,
        is_public=body.is_public,
    )
    return TemplateResponse(
        template_id=t.id,
        company_id=t.company_id,
        name=t.name,
        target_role=t.target_role,
        questions=t.questions,
        description=t.description,
        is_public=t.is_public,
        created_at=t.created_at,
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_and_company: tuple[User, Company] = Depends(get_current_company),
):
    _, company = user_and_company
    await delete_template(db, template_id, company.id)
