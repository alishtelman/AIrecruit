from __future__ import annotations

from app.ai.providers.base import LLMProvider
from app.ai.providers.openrouter_provider import OpenRouterProvider
from app.ai.providers.gemini_provider import GeminiProvider
from app.core.config import Settings


def get_llm_provider(settings: Settings) -> LLMProvider:
    provider_name = settings.ai_provider
    if provider_name == "openrouter":
        if settings.OPENROUTER_API_KEY:
            return OpenRouterProvider(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=settings.OPENROUTER_BASE_URL,
                default_model=settings.OPENROUTER_MODEL,
                fallback_models=settings.openrouter_fallback_models,
                site_url=settings.OPENROUTER_SITE_URL,
                app_name=settings.OPENROUTER_APP_NAME,
            )
        raise RuntimeError("AI_PROVIDER=openrouter but OPENROUTER_API_KEY is missing")

    if provider_name == "mock":
        raise RuntimeError("AI_PROVIDER=mock is not supported anymore")

    if provider_name == "gemini":
        if settings.GEMINI_API_KEY:
            return GeminiProvider(
                api_key=settings.GEMINI_API_KEY,
                default_model=settings.GEMINI_MODEL,
            )
        raise RuntimeError("AI_PROVIDER=gemini but GEMINI_API_KEY is missing")

    raise RuntimeError(f"Unknown AI_PROVIDER: {provider_name}")
