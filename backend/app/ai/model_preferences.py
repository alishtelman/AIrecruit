from __future__ import annotations

from app.core.config import settings

DEFAULT_LLM_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat-v3-0324:free"

ALLOWED_LLM_MODELS = {
    DEFAULT_LLM_MODEL,
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
}


def normalize_llm_model_preference(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def is_allowed_llm_model_preference(value: str | None) -> bool:
    normalized = normalize_llm_model_preference(value)
    if settings.ai_provider == "openrouter":
        return bool(normalized and len(normalized) <= 160)
    return normalized in ALLOWED_LLM_MODELS


def resolve_llm_runtime_model(value: str | None) -> str:
    normalized = normalize_llm_model_preference(value)
    if settings.ai_provider == "openrouter":
        if normalized:
            return normalized
        if settings.OPENROUTER_MODEL.strip():
            return settings.OPENROUTER_MODEL.strip()
        fallback_models = settings.openrouter_fallback_models
        if fallback_models:
            return fallback_models[0]
        return DEFAULT_OPENROUTER_MODEL
    if normalized in ALLOWED_LLM_MODELS:
        return normalized
    return DEFAULT_LLM_MODEL
