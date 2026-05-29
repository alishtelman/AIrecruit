from __future__ import annotations

from app.core.config import settings

DEFAULT_LLM_MODEL = "gemini-2.5-flash"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat-v3-0324:free"

DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0

DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_LLM_MODELS_BY_PROVIDER = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "openrouter": "openrouter/free",
}

ALLOWED_LLM_MODELS_BY_PROVIDER = {
    "gemini": (
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ),
    "openai": ("gpt-4.1-mini", "gpt-4.1"),
    "anthropic": ("claude-sonnet-4-20250514", "claude-haiku-4-20250514"),
    "openrouter": (),
}

ALLOWED_LLM_MODELS = set(ALLOWED_LLM_MODELS_BY_PROVIDER["gemini"])


def normalize_llm_model_preference(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def normalize_llm_provider(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized or DEFAULT_LLM_PROVIDER


def is_allowed_llm_provider(value: str | None) -> bool:
    return normalize_llm_provider(value) in ALLOWED_LLM_MODELS_BY_PROVIDER


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


def is_allowed_provider_model(provider: str | None, model: str | None) -> bool:
    normalized_provider = normalize_llm_provider(provider)
    normalized_model = normalize_llm_model_preference(model)
    return bool(
        normalized_model
        and normalized_model in ALLOWED_LLM_MODELS_BY_PROVIDER.get(normalized_provider, ())
    )


def default_model_for_provider(provider: str | None) -> str:
    normalized_provider = normalize_llm_provider(provider)
    return DEFAULT_LLM_MODELS_BY_PROVIDER.get(normalized_provider, DEFAULT_LLM_MODEL)


def resolve_provider_model(provider: str | None, model: str | None) -> str:
    normalized_provider = normalize_llm_provider(provider)
    normalized_model = normalize_llm_model_preference(model)
    if normalized_model in ALLOWED_LLM_MODELS_BY_PROVIDER.get(normalized_provider, ()):
        return normalized_model
    return default_model_for_provider(normalized_provider)


def model_options_payload() -> dict[str, list[str]]:
    return {
        provider: list(models)
        for provider, models in ALLOWED_LLM_MODELS_BY_PROVIDER.items()
    }


def validate_provider_model_payload(provider: str | None, model: str | None, *, field_name: str) -> None:
    normalized_provider = normalize_llm_provider(provider)
    if normalized_provider not in ALLOWED_LLM_MODELS_BY_PROVIDER:
        raise ValueError("Unsupported LLM provider")
    if not is_allowed_provider_model(normalized_provider, model):
        raise ValueError(f"Unsupported {field_name} for provider '{normalized_provider}'")


def safe_llm_runtime_payload(payload: dict[str, Any]) -> dict[str, Any]:
    provider = normalize_llm_provider(payload.get("llm_provider"))
    if provider not in ALLOWED_LLM_MODELS_BY_PROVIDER:
        provider = DEFAULT_LLM_PROVIDER
    return {
        "llm_provider": provider,
        "interviewer_model": resolve_provider_model(provider, payload.get("interviewer_model")),
        "assessor_model": resolve_provider_model(provider, payload.get("assessor_model")),
        "llm_timeout_seconds": int(payload.get("llm_timeout_seconds") or DEFAULT_LLM_TIMEOUT_SECONDS),
        "llm_max_retries": int(payload.get("llm_max_retries") or DEFAULT_LLM_MAX_RETRIES),
        "interviewer_prompt_override": normalize_llm_model_preference(payload.get("interviewer_prompt_override")),
        "assessor_prompt_override": normalize_llm_model_preference(payload.get("assessor_prompt_override")),
    }
