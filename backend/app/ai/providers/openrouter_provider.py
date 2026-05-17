from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.ai.providers.base import (
    LLMProvider,
    ProviderAttempt,
    ProviderChatCompletionResult,
    ProviderChatError,
)


_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_RETRYABLE_ERROR_HINTS = (
    "model_not_found",
    "rate_limit",
    "insufficient_quota",
    "provider_error",
    "timeout",
)


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        fallback_models: list[str],
        site_url: str,
        app_name: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._api_key = str(api_key or "").strip()
        self._base_url = str(base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self._default_model = str(default_model or "").strip()
        self._fallback_models = [str(item).strip() for item in fallback_models if str(item).strip()]
        self._site_url = str(site_url or "http://localhost:3000").strip()
        self._app_name = str(app_name or "AI Talent Verification Platform").strip()
        self._timeout_seconds = float(timeout_seconds)

    @property
    def configured_model(self) -> str:
        if self._default_model:
            return self._default_model
        return self._fallback_models[0] if self._fallback_models else ""

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _candidate_models(self, model_override: str | None) -> list[str]:
        requested = str(model_override or "").strip()
        models: list[str] = []
        if requested:
            models.append(requested)
        if self._default_model and self._default_model not in models:
            models.append(self._default_model)
        for item in self._fallback_models:
            if item and item not in models:
                models.append(item)
        return models

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            first_call = tool_calls[0] if isinstance(tool_calls[0], dict) else None
            function = first_call.get("function") if isinstance(first_call, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text.strip())
            return "\n".join(chunks).strip()
        return ""

    @staticmethod
    def _extract_error_message(payload: dict[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = str(error.get("code") or "").strip()
            if message and code:
                return f"{code}: {message}"
            if message:
                return message
            if code:
                return code
        return "openrouter_error"

    def _is_retryable_http_error(self, *, status_code: int, message: str) -> bool:
        lowered = (message or "").lower()
        if status_code in _RETRYABLE_STATUS:
            return True
        return any(hint in lowered for hint in _RETRYABLE_ERROR_HINTS)

    async def _call_model(
        self,
        *,
        model_name: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        extra_body: dict[str, Any] | None,
    ) -> ProviderChatCompletionResult:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._site_url,
            "X-Title": self._app_name,
        }
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            try:
                error_payload = response.json()
            except Exception:
                error_payload = {"error": {"message": response.text}}
            message = self._extract_error_message(error_payload)
            retryable = self._is_retryable_http_error(status_code=response.status_code, message=message)
            code = "retryable_http_error" if retryable else "provider_error"
            raise ProviderChatError(f"{response.status_code} {message}", code=code)

        try:
            body = response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - provider malformed payload is rare
            raise ProviderChatError(f"Invalid JSON from OpenRouter: {exc}", code="provider_error") from exc

        text = self._extract_text(body)
        if not text:
            raise ProviderChatError("Empty response content", code="provider_error")

        return ProviderChatCompletionResult(
            text=text,
            requested_model=model_name,
            actual_model_used=model_name,
            provider_attempts=[{"model": model_name, "ok": True, "error": None}],
            provider_errors=[],
            fallback_used=False,
            raw_response=body,
        )

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
        if not self.is_configured:
            raise ProviderChatError("OpenRouter provider is not configured", code="not_configured")

        models = self._candidate_models(model)
        if not models:
            raise ProviderChatError("No OpenRouter models configured", code="model_not_configured")

        requested_model = str(model or "").strip() or models[0]
        attempts: list[ProviderAttempt] = []
        errors: list[str] = []

        for idx, model_name in enumerate(models):
            # Brief pause between fallback attempts to respect free-tier rate limits
            if idx > 0:
                await asyncio.sleep(3.0)
            try:
                result = await self._call_model(
                    model_name=model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    extra_body=extra_body,
                )
                attempts.append(ProviderAttempt(model=model_name, ok=True))
                return ProviderChatCompletionResult(
                    text=result.text,
                    requested_model=requested_model,
                    actual_model_used=model_name,
                    provider_attempts=[
                        {"model": attempt.model, "ok": attempt.ok, "error": attempt.error}
                        for attempt in attempts
                    ],
                    provider_errors=errors,
                    fallback_used=idx > 0,
                    raw_response=result.raw_response,
                )
            except (ProviderChatError, httpx.TimeoutException, asyncio.TimeoutError, httpx.RequestError) as exc:
                err = str(exc)
                attempts.append(ProviderAttempt(model=model_name, ok=False, error=err))
                errors.append(f"{model_name}: {err}")
                continue

        raise ProviderChatError(
            f"OpenRouter completion failed for all models ({'; '.join(errors)})",
            code="all_models_failed",
        )
