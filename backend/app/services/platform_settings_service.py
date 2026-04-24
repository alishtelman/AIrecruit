from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform_settings import PlatformSettings

_ALLOWED_PROCTORING_POLICY_MODES = {"observe_only", "strict_flagging"}


def _normalize_model_preference(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


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
    )
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created


async def get_platform_settings_payload(db: AsyncSession) -> dict[str, Any]:
    row = await get_or_create_platform_settings(db)
    return {
        "candidate_registration_enabled": row.candidate_registration_enabled,
        "company_registration_enabled": row.company_registration_enabled,
        "employee_invites_enabled": row.employee_invites_enabled,
        "maintenance_mode_enabled": row.maintenance_mode_enabled,
        "proctoring_policy_mode": _normalize_policy_mode(row.proctoring_policy_mode),
        "interviewer_model_preference": _normalize_model_preference(row.interviewer_model_preference),
        "assessor_model_preference": _normalize_model_preference(row.assessor_model_preference),
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
) -> dict[str, Any]:
    row = await get_or_create_platform_settings(db)
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

    await db.commit()
    await db.refresh(row)
    return await get_platform_settings_payload(db)


async def candidate_registration_enabled(db: AsyncSession) -> bool:
    row = await get_or_create_platform_settings(db)
    return row.candidate_registration_enabled


async def company_registration_enabled(db: AsyncSession) -> bool:
    row = await get_or_create_platform_settings(db)
    return row.company_registration_enabled


async def employee_invites_enabled(db: AsyncSession) -> bool:
    row = await get_or_create_platform_settings(db)
    return row.employee_invites_enabled


async def build_effective_workspace_ai_settings(
    db: AsyncSession,
    workspace_ai_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = await get_or_create_platform_settings(db)
    payload = {
        "proctoring_policy_mode": _normalize_policy_mode(row.proctoring_policy_mode),
        "interviewer_model_preference": _normalize_model_preference(row.interviewer_model_preference),
        "assessor_model_preference": _normalize_model_preference(row.assessor_model_preference),
    }
    if isinstance(workspace_ai_settings, Mapping):
        for key in ("proctoring_policy_mode", "interviewer_model_preference", "assessor_model_preference"):
            value = workspace_ai_settings.get(key)
            if value in (None, ""):
                continue
            if key == "proctoring_policy_mode":
                payload[key] = _normalize_policy_mode(str(value))
            else:
                payload[key] = _normalize_model_preference(str(value))
    return payload
