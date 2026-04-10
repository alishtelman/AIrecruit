from __future__ import annotations

DEFAULT_LLM_MODEL = "llama-3.3-70b-versatile"

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
    return normalized in ALLOWED_LLM_MODELS


def resolve_llm_runtime_model(value: str | None) -> str:
    normalized = normalize_llm_model_preference(value)
    if normalized in ALLOWED_LLM_MODELS:
        return normalized
    return DEFAULT_LLM_MODEL
