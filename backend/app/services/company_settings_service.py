from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.company import Company
from app.services.platform_settings_service import get_platform_settings_payload

_ALLOWED_PROCTORING_POLICY_MODES = {"observe_only", "strict_flagging"}


async def get_company_ai_settings_response(db: AsyncSession, company: Company) -> dict[str, Any]:
    platform_settings = await get_platform_settings_payload(db)
    configured_policy = str(platform_settings.get("proctoring_policy_mode") or "").strip().lower()
    if configured_policy not in _ALLOWED_PROCTORING_POLICY_MODES:
        configured_policy = "observe_only"

    return {
        "proctoring_policy_mode": configured_policy,
        "managed_by": "platform_admin",
        "message": "AI runtime is managed by platform admin.",
        "tts_provider": settings.TTS_PROVIDER,
        "tts_fallback_provider": settings.TTS_FALLBACK_PROVIDER,
        "mock_ai_available": settings.allow_mock_ai,
        "runtime_applied_fields": [],
        "stored_preference_fields": [],
    }
