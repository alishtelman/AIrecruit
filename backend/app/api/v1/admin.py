from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_platform_admin, get_db
from app.models.user import User
from app.schemas.admin import AdminOverviewResponse
from app.services.admin_service import get_admin_overview

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    _: User = Depends(get_current_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_admin_overview(db)
