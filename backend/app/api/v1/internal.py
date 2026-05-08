from fastapi import APIRouter, Header, HTTPException, Query, status

from app.core.config import settings
from app.services.interview_service import (
    get_external_report_worker_status,
    run_next_external_report_generation_job,
)

router = APIRouter(prefix="/internal/report-worker", tags=["internal"])


def _verify_worker_token(token: str | None) -> None:
    expected = settings.INTERNAL_WORKER_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal worker token is not configured.",
        )
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal worker token.",
        )


@router.post("/tick")
async def run_report_worker_tick(
    dry_run: bool = Query(default=False),
    x_internal_worker_token: str | None = Header(default=None),
) -> dict:
    _verify_worker_token(x_internal_worker_token)
    return await run_next_external_report_generation_job(dry_run=dry_run)


@router.get("/status")
async def get_report_worker_status(
    x_internal_worker_token: str | None = Header(default=None),
) -> dict:
    _verify_worker_token(x_internal_worker_token)
    return await get_external_report_worker_status()
