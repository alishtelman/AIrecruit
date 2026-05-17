from __future__ import annotations

from typing import Any

from groq import AsyncGroq

from app.ai.model_preferences import DEFAULT_LLM_MODEL, resolve_llm_runtime_model
from app.ai.providers.base import (
    LLMProvider,
    ProviderAttempt,
    ProviderChatCompletionResult,
    ProviderChatError,
)


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, *, api_key: str) -> None:
        self._api_key = str(api_key or "").strip()
        self._client = AsyncGroq(api_key=self._api_key) if self._api_key else None

    @property
    def configured_model(self) -> str:
        return DEFAULT_LLM_MODEL

    @property
    def is_configured(self) -> bool:
        return bool(self._client)

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> ProviderChatCompletionResult:
        if not self._client:
            raise ProviderChatError("Groq provider is not configured", code="not_configured")

        requested_model = resolve_llm_runtime_model(model)
        models = [requested_model]
        if requested_model != DEFAULT_LLM_MODEL:
            models.append(DEFAULT_LLM_MODEL)

        attempts: list[ProviderAttempt] = []
        errors: list[str] = []
        for idx, model_name in enumerate(models):
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if response_format is not None:
                    kwargs["response_format"] = response_format
                if isinstance(extra_body, dict):
                    kwargs.update(extra_body)
                response = await self._client.chat.completions.create(**kwargs)
                message = response.choices[0].message
                raw_text = str(message.content or "").strip()
                if not raw_text:
                    tool_calls = getattr(message, "tool_calls", None)
                    if tool_calls:
                        try:
                            raw_text = str(tool_calls[0].function.arguments or "").strip()
                        except Exception:
                            raw_text = ""
                if not raw_text:
                    raise ProviderChatError("Empty response content", code="empty_response")
                attempts.append(ProviderAttempt(model=model_name, ok=True))
                return ProviderChatCompletionResult(
                    text=raw_text,
                    requested_model=requested_model,
                    actual_model_used=model_name,
                    provider_attempts=[{"model": attempt.model, "ok": attempt.ok, "error": attempt.error} for attempt in attempts],
                    provider_errors=errors,
                    fallback_used=idx > 0,
                    raw_response=response,
                )
            except Exception as exc:  # pragma: no cover - branch depends on external provider behavior
                attempts.append(ProviderAttempt(model=model_name, ok=False, error=str(exc)))
                errors.append(f"{model_name}: {exc}")

        raise ProviderChatError(
            "Groq completion failed for all attempts",
            code="all_models_failed",
        )
