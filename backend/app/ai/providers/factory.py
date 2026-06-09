from __future__ import annotations

from app.ai.providers.base import LLMProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.core.config import Settings


def get_llm_provider(settings: Settings) -> LLMProvider:
    provider_name = settings.ai_provider
    if provider_name == "openai":
        if settings.OPENAI_API_KEY:
            return OpenAIProvider(
                api_key=settings.OPENAI_API_KEY,
                default_model=settings.OPENAI_MODEL,
                reasoning_effort=settings.OPENAI_REASONING_EFFORT,
                base_url=settings.OPENAI_BASE_URL,
            )
        raise RuntimeError("AI_PROVIDER=openai but OPENAI_API_KEY is missing")

    raise RuntimeError("Only AI_PROVIDER=openai is supported")
