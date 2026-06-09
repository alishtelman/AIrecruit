from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model_preferences import is_allowed_llm_model_preference
from app.core.config import settings
from app.models.company import Company
from app.services.platform_settings_service import get_platform_proctoring_policy_mode

_ALLOWED_PROCTORING_POLICY_MODES = {"observe_only", "strict_flagging"}


def _runtime_provider_name() -> str:
    provider = settings.ai_provider
    if provider == "openai" and settings.OPENAI_API_KEY:
        return "openai"
    return "disabled"


def _normalized_company_ai_settings(company: Company) -> dict[str, Any]:
    payload = company.ai_settings if isinstance(company.ai_settings, dict) else {}
    normalized: dict[str, Any] = {}

    proctoring_policy_mode = str(payload.get("proctoring_policy_mode") or "").strip().lower()
    if proctoring_policy_mode in _ALLOWED_PROCTORING_POLICY_MODES:
        normalized["proctoring_policy_mode"] = proctoring_policy_mode

    for key in ("interviewer_model_preference", "assessor_model_preference"):
        value = str(payload.get(key) or "").strip()
        if value:
            normalized[key] = value[:120]

    return normalized


def get_company_ai_settings_response(company: Company) -> dict[str, Any]:
    stored = _normalized_company_ai_settings(company)
    provider = _runtime_provider_name()
    runtime_applied_fields = ["proctoring_policy_mode"]
    stored_preference_fields = [key for key in stored.keys() if key != "proctoring_policy_mode"]
    if is_allowed_llm_model_preference(stored.get("interviewer_model_preference")):
        runtime_applied_fields.append("interviewer_model_preference")
    if is_allowed_llm_model_preference(stored.get("assessor_model_preference")):
        runtime_applied_fields.append("assessor_model_preference")

    configured_policy = (settings.PROCTORING_POLICY_MODE or "").strip().lower()
    if configured_policy not in _ALLOWED_PROCTORING_POLICY_MODES:
        configured_policy = "observe_only"

    return {
        "proctoring_policy_mode": configured_policy,
        "managed_by": "platform_admin",
        "message": "AI runtime is managed by platform admin.",
        "tts_provider": settings.TTS_PROVIDER,
        "tts_fallback_provider": settings.TTS_FALLBACK_PROVIDER,
        "runtime_applied_fields": [],
        "stored_preference_fields": [],
    }
