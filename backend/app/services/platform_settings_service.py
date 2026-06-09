from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ai.model_preferences import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    default_model_for_provider,
    model_options_payload,
    is_allowed_provider_model,
    normalize_llm_model_preference,
    normalize_llm_provider,
    resolve_provider_model,
    validate_provider_model_payload,
)
from app.models.platform_settings import PlatformSettings

_ALLOWED_PROCTORING_POLICY_MODES = {"observe_only", "strict_flagging"}
_PROVIDERS_REQUIRING_KEYS = {
    "openai": "OPENAI_API_KEY",
}


def _normalize_model_preference(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_prompt_override(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_timeout_seconds(value: int | None) -> int:
    try:
        normalized = int(value or DEFAULT_LLM_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        normalized = DEFAULT_LLM_TIMEOUT_SECONDS
    return min(max(normalized, 5), 120)


def _normalize_max_retries(value: int | None) -> int:
    try:
        normalized = int(value if value is not None else DEFAULT_LLM_MAX_RETRIES)
    except (TypeError, ValueError):
        normalized = DEFAULT_LLM_MAX_RETRIES
    return min(max(normalized, 0), 5)


def _api_key_available(provider: str) -> bool:
    if provider == "openai":
        return bool(settings.OPENAI_API_KEY)
    return False


def _resolve_provider_key_status(
    provider: str,
    provider_statuses: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[bool, str | None]:
    _ = provider_statuses
    required_key = _PROVIDERS_REQUIRING_KEYS.get(provider)
    return _api_key_available(provider), required_key


def _normalize_policy_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_PROCTORING_POLICY_MODES:
        return normalized
    configured = str(settings.PROCTORING_POLICY_MODE or "").strip().lower()
    if configured in _ALLOWED_PROCTORING_POLICY_MODES:
        return configured
    return "observe_only"


async def get_or_create_platform_settings(db: AsyncSession) -> PlatformSettings:
    existing = await db.scalar(select(PlatformSettings).where(PlatformSettings.id == 1))
    if existing:
        return existing

    created = PlatformSettings(
        id=1,
        candidate_registration_enabled=True,
        company_registration_enabled=True,
        employee_invites_enabled=True,
        maintenance_mode_enabled=False,
        proctoring_policy_mode=_normalize_policy_mode(settings.PROCTORING_POLICY_MODE),
        interviewer_model_preference=None,
        assessor_model_preference=None,
        llm_provider=DEFAULT_LLM_PROVIDER,
        interviewer_model=default_model_for_provider(DEFAULT_LLM_PROVIDER),
        assessor_model=default_model_for_provider(DEFAULT_LLM_PROVIDER),
        interviewer_prompt_override=None,
        assessor_prompt_override=None,
        llm_timeout_seconds=DEFAULT_LLM_TIMEOUT_SECONDS,
        llm_max_retries=DEFAULT_LLM_MAX_RETRIES,
    )
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created


async def get_platform_settings_payload(db: AsyncSession) -> dict[str, Any]:
    row = await get_or_create_platform_settings(db)
    provider = normalize_llm_provider(row.llm_provider)
    if provider not in model_options_payload():
        provider = DEFAULT_LLM_PROVIDER
    interviewer_model = resolve_provider_model(
        provider,
        row.interviewer_model or row.interviewer_model_preference,
    )
    assessor_model = resolve_provider_model(
        provider,
        row.assessor_model or row.assessor_model_preference,
    )
    key_available, required_key = _resolve_provider_key_status(provider)
    return {
        "candidate_registration_enabled": row.candidate_registration_enabled,
        "company_registration_enabled": row.company_registration_enabled,
        "employee_invites_enabled": row.employee_invites_enabled,
        "maintenance_mode_enabled": row.maintenance_mode_enabled,
        "proctoring_policy_mode": _normalize_policy_mode(row.proctoring_policy_mode),
        "interviewer_model_preference": _normalize_model_preference(row.interviewer_model_preference),
        "assessor_model_preference": _normalize_model_preference(row.assessor_model_preference),
        "llm_provider": provider,
        "interviewer_model": interviewer_model,
        "assessor_model": assessor_model,
        "interviewer_prompt_override": _normalize_prompt_override(row.interviewer_prompt_override),
        "assessor_prompt_override": _normalize_prompt_override(row.assessor_prompt_override),
        "llm_timeout_seconds": _normalize_timeout_seconds(row.llm_timeout_seconds),
        "llm_max_retries": _normalize_max_retries(row.llm_max_retries),
        "llm_model_options": model_options_payload(),
        "llm_api_key_available": key_available,
        "llm_required_api_key": required_key,
        "llm_configuration_warning": None if key_available else f"{required_key or 'API key'} is not configured",
        "tts_provider": settings.TTS_PROVIDER,
        "tts_fallback_provider": settings.TTS_FALLBACK_PROVIDER,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def update_platform_settings(
    db: AsyncSession,
    *,
    candidate_registration_enabled: bool | None = None,
    company_registration_enabled: bool | None = None,
    employee_invites_enabled: bool | None = None,
    maintenance_mode_enabled: bool | None = None,
    proctoring_policy_mode: str | None = None,
    interviewer_model_preference: str | None = None,
    assessor_model_preference: str | None = None,
    llm_provider: str | None = None,
    interviewer_model: str | None = None,
    assessor_model: str | None = None,
    interviewer_prompt_override: str | None = None,
    assessor_prompt_override: str | None = None,
    llm_timeout_seconds: int | None = None,
    llm_max_retries: int | None = None,
) -> dict[str, Any]:
    row = await get_or_create_platform_settings(db)
    current_db_provider = normalize_llm_provider(row.llm_provider)
    if current_db_provider not in model_options_payload():
        current_db_provider = DEFAULT_LLM_PROVIDER
    target_provider = normalize_llm_provider(llm_provider) if llm_provider is not None else current_db_provider
    if target_provider not in model_options_payload():
        raise ValueError("Unsupported LLM provider")
    target_interviewer_model = interviewer_model
    if target_interviewer_model is None:
        target_interviewer_model = row.interviewer_model or row.interviewer_model_preference
    if not is_allowed_provider_model(target_provider, target_interviewer_model):
        target_interviewer_model = default_model_for_provider(target_provider)

    target_assessor_model = assessor_model
    if target_assessor_model is None:
        target_assessor_model = row.assessor_model or row.assessor_model_preference
    if not is_allowed_provider_model(target_provider, target_assessor_model):
        target_assessor_model = default_model_for_provider(target_provider)
    validate_provider_model_payload(target_provider, target_interviewer_model, field_name="interviewer_model")
    validate_provider_model_payload(target_provider, target_assessor_model, field_name="assessor_model")

    if candidate_registration_enabled is not None:
        row.candidate_registration_enabled = bool(candidate_registration_enabled)
    if company_registration_enabled is not None:
        row.company_registration_enabled = bool(company_registration_enabled)
    if employee_invites_enabled is not None:
        row.employee_invites_enabled = bool(employee_invites_enabled)
    if maintenance_mode_enabled is not None:
        row.maintenance_mode_enabled = bool(maintenance_mode_enabled)
    if proctoring_policy_mode is not None:
        row.proctoring_policy_mode = _normalize_policy_mode(proctoring_policy_mode)
    if interviewer_model_preference is not None:
        row.interviewer_model_preference = _normalize_model_preference(interviewer_model_preference)
    if assessor_model_preference is not None:
        row.assessor_model_preference = _normalize_model_preference(assessor_model_preference)
    if llm_provider is not None:
        row.llm_provider = target_provider
    if interviewer_model is not None or llm_provider is not None:
        row.interviewer_model = normalize_llm_model_preference(target_interviewer_model)
        row.interviewer_model_preference = row.interviewer_model
    if assessor_model is not None or llm_provider is not None:
        row.assessor_model = normalize_llm_model_preference(target_assessor_model)
        row.assessor_model_preference = row.assessor_model
    if interviewer_prompt_override is not None:
        row.interviewer_prompt_override = _normalize_prompt_override(interviewer_prompt_override)
    if assessor_prompt_override is not None:
        row.assessor_prompt_override = _normalize_prompt_override(assessor_prompt_override)
    if llm_timeout_seconds is not None:
        row.llm_timeout_seconds = _normalize_timeout_seconds(llm_timeout_seconds)
    if llm_max_retries is not None:
        row.llm_max_retries = _normalize_max_retries(llm_max_retries)

    await db.commit()
    await db.refresh(row)
    return await get_platform_settings_payload(db)


async def candidate_registration_enabled(db: AsyncSession) -> bool:
    row = await get_or_create_platform_settings(db)
    return row.candidate_registration_enabled


async def company_registration_enabled(db: AsyncSession) -> bool:
    row = await get_or_create_platform_settings(db)
    return row.company_registration_enabled


async def get_platform_proctoring_policy_mode(db: AsyncSession) -> str:
    row = await get_or_create_platform_settings(db)
    return _normalize_policy_mode(row.proctoring_policy_mode)


async def employee_invites_enabled(db: AsyncSession) -> bool:
    row = await get_or_create_platform_settings(db)
    return row.employee_invites_enabled


async def build_effective_workspace_ai_settings(
    db: AsyncSession,
    workspace_ai_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = await get_or_create_platform_settings(db)
    provider = normalize_llm_provider(row.llm_provider)
    if provider not in model_options_payload():
        provider = DEFAULT_LLM_PROVIDER
    payload = {
        "proctoring_policy_mode": _normalize_policy_mode(row.proctoring_policy_mode),
        "llm_provider": provider,
        "interviewer_model": resolve_provider_model(provider, row.interviewer_model or row.interviewer_model_preference),
        "assessor_model": resolve_provider_model(provider, row.assessor_model or row.assessor_model_preference),
        "interviewer_model_preference": resolve_provider_model(provider, row.interviewer_model or row.interviewer_model_preference),
        "assessor_model_preference": resolve_provider_model(provider, row.assessor_model or row.assessor_model_preference),
        "interviewer_prompt_override": _normalize_prompt_override(row.interviewer_prompt_override),
        "assessor_prompt_override": _normalize_prompt_override(row.assessor_prompt_override),
        "llm_timeout_seconds": _normalize_timeout_seconds(row.llm_timeout_seconds),
        "llm_max_retries": _normalize_max_retries(row.llm_max_retries),
    }
    return payload
