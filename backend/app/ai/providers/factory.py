from __future__ import annotations

from app.ai.providers.base import LLMProvider
from app.ai.providers.groq_provider import GroqProvider
from app.ai.providers.mock_provider import MockProvider
from app.ai.providers.openrouter_provider import OpenRouterProvider
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
        if settings.allow_mock_ai:
            return MockProvider()
        raise RuntimeError("AI_PROVIDER=openrouter but OPENROUTER_API_KEY is missing")

    if provider_name == "mock":
        if settings.allow_mock_ai:
            return MockProvider()
        raise RuntimeError("AI_PROVIDER=mock is disabled outside local/test")

    # default: groq
    if settings.GROQ_API_KEY:
        return GroqProvider(api_key=settings.GROQ_API_KEY)
    if settings.allow_mock_ai:
        return MockProvider()
    raise RuntimeError("AI_PROVIDER=groq but GROQ_API_KEY is missing")
