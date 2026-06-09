import asyncio
import logging
import time
from typing import Any

import httpx

from app.ai.providers.base import (
    LLMProvider,
    ProviderChatCompletionResult,
    ProviderChatError,
)

logger = logging.getLogger(__name__)

# Model families that are OpenAI "reasoning" models. They use the Chat
# Completions API differently: `max_completion_tokens` instead of `max_tokens`,
# they reject a custom `temperature` (only the default is allowed), and they
# spend billable output tokens on internal reasoning. `reasoning_effort` lets us
# keep that spend (and latency) under control.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return any(name.startswith(prefix) for prefix in _REASONING_MODEL_PREFIXES)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-5.4-mini",
        *,
        reasoning_effort: str = "low",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._reasoning_effort = (reasoning_effort or "low").strip().lower() or "low"
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60.0)

    @property
    def configured_model(self) -> str:
        return self._default_model

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ProviderChatCompletionResult:
        actual_model = model or self._default_model
        if not self._api_key:
            logger.error(
                "openai_call status=error provider=openai model=%s error=not_configured",
                actual_model,
            )
            raise ProviderChatError("OpenAI provider is not configured", code="not_configured")

        is_reasoning = _is_reasoning_model(actual_model)

        payload: dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
        }

        if is_reasoning:
            # Reasoning tokens count against the completion budget; give generous
            # headroom so the visible answer is never starved. The cap is only an
            # upper bound — billing is on tokens actually produced.
            payload["max_completion_tokens"] = max(int(max_tokens or 0), 4096)
            payload["reasoning_effort"] = self._reasoning_effort
            # `temperature` is rejected by reasoning models — omit it.
        else:
            payload["max_tokens"] = int(max_tokens or 0)
            payload["temperature"] = temperature

        if response_format and response_format.get("type") == "json_object":
            payload["response_format"] = {"type": "json_object"}

        if extra_body:
            for key, value in extra_body.items():
                payload.setdefault(key, value)

        attempts: list[dict[str, Any]] = []
        errors: list[str] = []
        start_time = time.monotonic()
        logger.info(
            "openai_call status=start provider=openai model=%s reasoning=%s messages=%s max_tokens=%s",
            actual_model,
            is_reasoning,
            len(messages),
            payload.get("max_completion_tokens") or payload.get("max_tokens"),
        )

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        max_attempts = 5
        for attempt_idx in range(max_attempts):
            try:
                timeout_val = timeout if timeout is not None else (30.0 + (attempt_idx * 15.0))
                httpx_timeout = httpx.Timeout(timeout_val)
                resp = await self._client.post(url, headers=headers, json=payload, timeout=httpx_timeout)

                if resp.status_code == 429:
                    error_msg = f"OpenAI Rate Limit 429: {resp.text}"
                    errors.append(error_msg)
                    attempts.append({"model": actual_model, "ok": False, "error": error_msg})
                    delay = 5.0 * (attempt_idx + 1)
                    retry_after = resp.headers.get("retry-after")
                    if retry_after:
                        try:
                            delay = float(retry_after) + 1.0
                        except ValueError:
                            pass
                    logger.warning("OpenAI Rate Limit hit. Retrying in %.1fs...", delay)
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                data = resp.json()

                try:
                    choice = data["choices"][0]
                    text = choice["message"]["content"]
                except (KeyError, IndexError) as exc:
                    raise ProviderChatError(f"Unexpected response structure: {data}") from exc

                if not text:
                    finish_reason = ""
                    try:
                        finish_reason = str(data["choices"][0].get("finish_reason") or "")
                    except (KeyError, IndexError):
                        pass
                    raise ProviderChatError(
                        f"OpenAI returned empty content (finish_reason={finish_reason or 'unknown'})",
                        code="empty_response",
                    )

                usage = data.get("usage", {}) or {}
                req_tokens = int(usage.get("prompt_tokens", 0) or 0)
                res_tokens = int(usage.get("completion_tokens", 0) or 0)

                attempts.append({"model": actual_model, "ok": True, "error": None})
                latency_ms = (time.monotonic() - start_time) * 1000.0
                logger.info(
                    "openai_call status=success provider=openai model=%s latency_ms=%.1f prompt_tokens=%s completion_tokens=%s",
                    actual_model,
                    latency_ms,
                    req_tokens,
                    res_tokens,
                )

                return ProviderChatCompletionResult(
                    text=text,
                    requested_model=actual_model,
                    actual_model_used=str(data.get("model") or actual_model),
                    request_tokens_estimate=req_tokens,
                    response_tokens_estimate=res_tokens,
                    provider_latency_ms=latency_ms,
                    provider_attempts=attempts,
                    provider_errors=errors,
                    fallback_used=False,
                    raw_response=data,
                )

            except httpx.HTTPStatusError as exc:
                error_msg = f"HTTP {exc.response.status_code}: {exc.response.text}"
                errors.append(error_msg)
                attempts.append({"model": actual_model, "ok": False, "error": error_msg})
                # Client errors (bad request, auth, not found) are not retriable.
                if exc.response.status_code in {400, 401, 403, 404}:
                    break
            except ProviderChatError as exc:
                errors.append(str(exc))
                attempts.append({"model": actual_model, "ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - record and retry
                error_msg = f"Request failed: {exc}"
                errors.append(error_msg)
                attempts.append({"model": actual_model, "ok": False, "error": error_msg})

            await asyncio.sleep(2 + attempt_idx * 2)

        latency_ms = (time.monotonic() - start_time) * 1000.0
        last_error = errors[-1] if errors else "Unknown"
        logger.error(
            "openai_call status=error provider=openai model=%s latency_ms=%.1f error=%s",
            actual_model,
            latency_ms,
            last_error,
        )
        raise ProviderChatError(
            f"OpenAI completion failed for all attempts. Last error: {last_error}",
            code="openai_error",
        )
