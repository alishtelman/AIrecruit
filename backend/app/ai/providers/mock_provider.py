from __future__ import annotations

from app.ai.providers.base import LLMProvider, ProviderChatCompletionResult, ProviderChatError


class MockProvider(LLMProvider):
    name = "mock"

    @property
    def configured_model(self) -> str:
        return "mock-model"

    @property
    def is_configured(self) -> bool:
        return True

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict | None = None,
        extra_body: dict | None = None,
    ) -> ProviderChatCompletionResult:
        _ = (messages, model, temperature, max_tokens, response_format, extra_body)
        raise ProviderChatError("Mock provider does not generate LLM completions", code="mock_provider")
