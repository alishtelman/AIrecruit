from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.company import Company

_DEFAULT_LLM_MODEL = "llama-3.3-70b-versatile"
_ALLOWED_PROCTORING_POLICY_MODES = {"observe_only", "strict_flagging"}


def _runtime_provider_name() -> str:
    if settings.GROQ_API_KEY:
        return "groq"
    if settings.allow_mock_ai:
        return "mock"
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

    configured_policy = (settings.PROCTORING_POLICY_MODE or "").strip().lower()
    if configured_policy not in _ALLOWED_PROCTORING_POLICY_MODES:
        configured_policy = "observe_only"

    return {
        "proctoring_policy_mode": stored.get("proctoring_policy_mode") or configured_policy,
        "interviewer_provider": provider,
        "interviewer_runtime_model": _DEFAULT_LLM_MODEL if provider != "disabled" else "disabled",
        "interviewer_model_preference": stored.get("interviewer_model_preference"),
        "assessor_provider": provider,
        "assessor_runtime_model": _DEFAULT_LLM_MODEL if provider != "disabled" else "disabled",
        "assessor_model_preference": stored.get("assessor_model_preference"),
        "tts_provider": settings.TTS_PROVIDER,
        "tts_fallback_provider": settings.TTS_FALLBACK_PROVIDER,
        "mock_ai_available": settings.allow_mock_ai,
        "runtime_applied_fields": runtime_applied_fields,
        "stored_preference_fields": stored_preference_fields,
    }


async def update_company_ai_settings(
    db: AsyncSession,
    *,
    company: Company,
    updates: dict[str, Any],
) -> dict[str, Any]:
    payload = _normalized_company_ai_settings(company)

    for key in ("proctoring_policy_mode", "interviewer_model_preference", "assessor_model_preference"):
        if key in updates:
            value = updates.get(key)
            if value in (None, ""):
                payload.pop(key, None)
            else:
                payload[key] = value

    company.ai_settings = payload or None
    await db.commit()
    await db.refresh(company)
    return get_company_ai_settings_response(company)
