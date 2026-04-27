from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from groq import (
    APIConnectionError as GroqAPIConnectionError,
    APIStatusError as GroqAPIStatusError,
    APITimeoutError as GroqAPITimeoutError,
    AsyncGroq,
    AuthenticationError as GroqAuthenticationError,
    RateLimitError as GroqRateLimitError,
)

from app.ai.model_preferences import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    normalize_llm_provider,
    resolve_provider_model,
    validate_provider_model_payload,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

LLMErrorCategory = Literal[
    "configuration_error",
    "auth_error",
    "timeout_error",
    "rate_limit_error",
    "provider_error",
    "invalid_structured_output",
]


class LLMRuntimeError(RuntimeError):
    def __init__(self, category: LLMErrorCategory, message: str, *, retryable: bool = False) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class LLMRuntimeSettings:
    provider: str
    model: str
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_LLM_MAX_RETRIES
    prompt_override: str | None = None


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    provider: str
    raw: Any | None = None


def runtime_settings_from_payload(payload: dict[str, Any] | None, *, role: str) -> LLMRuntimeSettings:
    source = payload if isinstance(payload, dict) else {}
    provider = normalize_llm_provider(source.get("llm_provider"))
    model_key = "assessor_model" if role == "assessor" else "interviewer_model"
    legacy_key = "assessor_model_preference" if role == "assessor" else "interviewer_model_preference"
    prompt_key = "assessor_prompt_override" if role == "assessor" else "interviewer_prompt_override"
    model = resolve_provider_model(provider, source.get(model_key) or source.get(legacy_key))
    return LLMRuntimeSettings(
        provider=provider,
        model=model,
        timeout_seconds=int(source.get("llm_timeout_seconds") or DEFAULT_LLM_TIMEOUT_SECONDS),
        max_retries=int(source.get("llm_max_retries") or DEFAULT_LLM_MAX_RETRIES),
        prompt_override=str(source.get(prompt_key) or "").strip() or None,
    )


def _api_key_for_provider(provider: str) -> str:
    if provider == "groq":
        return settings.GROQ_API_KEY
    if provider == "openai":
        return settings.OPENAI_API_KEY
    if provider == "anthropic":
        return settings.ANTHROPIC_API_KEY
    return ""


def _required_key_name(provider: str) -> str:
    return {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider, "API key")


def _normalize_messages(messages: list[dict[str, Any]], prompt_override: str | None) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    normalized: list[dict[str, str]] = []
    if prompt_override:
        system_parts.append(prompt_override)
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            if not prompt_override:
                system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        normalized.append({"role": role, "content": content})
    return ("\n\n".join(system_parts) if system_parts else None), normalized


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMRuntimeError("invalid_structured_output", "Provider returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMRuntimeError("invalid_structured_output", "Provider returned non-object JSON")
    return parsed


class LLMRuntime:
    async def complete_text(
        self,
        *,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        return await self._with_retries(
            runtime_settings,
            lambda: self._complete_text_once(
                runtime_settings=runtime_settings,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
        )

    async def complete_structured(
        self,
        *,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        tool: dict[str, Any],
    ) -> tuple[dict[str, Any], LLMResult]:
        result = await self._with_retries(
            runtime_settings,
            lambda: self._complete_structured_once(
                runtime_settings=runtime_settings,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tool=tool,
            ),
        )
        return _extract_json(result.text), result

    async def _with_retries(self, runtime_settings: LLMRuntimeSettings, call):
        attempts = max(runtime_settings.max_retries, 0) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await call()
            except LLMRuntimeError as exc:
                last_error = exc
                if exc.category not in {"timeout_error", "rate_limit_error"} and not exc.retryable:
                    raise
                if attempt >= attempts - 1:
                    raise
            except (httpx.TimeoutException, httpx.NetworkError, GroqAPITimeoutError, GroqAPIConnectionError) as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    raise LLMRuntimeError("timeout_error", "LLM provider request timed out or failed on network") from exc
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        raise LLMRuntimeError("provider_error", "LLM provider request failed") from last_error

    def _validate_runtime(self, runtime_settings: LLMRuntimeSettings) -> None:
        provider = normalize_llm_provider(runtime_settings.provider)
        validate_provider_model_payload(provider, runtime_settings.model, field_name="model")
        if not _api_key_for_provider(provider):
            raise LLMRuntimeError(
                "configuration_error",
                f"{_required_key_name(provider)} is not configured for selected LLM provider '{provider}'",
            )

    async def _complete_text_once(
        self,
        *,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        self._validate_runtime(runtime_settings)
        if runtime_settings.provider == "groq":
            return await self._groq_chat(runtime_settings, messages, max_tokens=max_tokens, temperature=temperature)
        if runtime_settings.provider == "openai":
            return await self._openai_response(runtime_settings, messages, max_tokens=max_tokens, temperature=temperature)
        if runtime_settings.provider == "anthropic":
            return await self._anthropic_message(runtime_settings, messages, max_tokens=max_tokens, temperature=temperature)
        raise LLMRuntimeError("configuration_error", f"Unsupported LLM provider '{runtime_settings.provider}'")

    async def _complete_structured_once(
        self,
        *,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        tool: dict[str, Any],
    ) -> LLMResult:
        self._validate_runtime(runtime_settings)
        if runtime_settings.provider == "groq":
            return await self._groq_chat(
                runtime_settings,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}},
            )
        schema = tool.get("function", {}).get("parameters") or {}
        tool_name = tool.get("function", {}).get("name") or "submit_result"
        tool_description = tool.get("function", {}).get("description") or "Return structured JSON."
        structured_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    f"Return only valid JSON for `{tool_name}`. {tool_description}\n"
                    f"JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
                ),
            },
        ]
        if runtime_settings.provider == "openai":
            return await self._openai_response(
                runtime_settings,
                structured_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_schema={"name": tool_name, "schema": schema, "strict": False},
            )
        if runtime_settings.provider == "anthropic":
            return await self._anthropic_message(
                runtime_settings,
                structured_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        raise LLMRuntimeError("configuration_error", f"Unsupported LLM provider '{runtime_settings.provider}'")

    async def _groq_chat(
        self,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> LLMResult:
        try:
            system, chat_messages = _normalize_messages(messages, runtime_settings.prompt_override)
            if system:
                chat_messages.insert(0, {"role": "system", "content": system})
            client = AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=runtime_settings.timeout_seconds)
            response = await client.chat.completions.create(
                model=runtime_settings.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=chat_messages,
                **({"tools": tools, "tool_choice": tool_choice} if tools else {}),
            )
            message = response.choices[0].message
            if tools:
                tool_calls = getattr(message, "tool_calls", None) or []
                if not tool_calls:
                    raise LLMRuntimeError("invalid_structured_output", "Groq did not return a tool call")
                text = tool_calls[0].function.arguments
            else:
                text = message.content or ""
            return LLMResult(text=text.strip(), model=runtime_settings.model, provider="groq", raw=response)
        except GroqAuthenticationError as exc:
            raise LLMRuntimeError("auth_error", "Groq authentication failed") from exc
        except GroqRateLimitError as exc:
            raise LLMRuntimeError("rate_limit_error", "Groq rate limit exceeded") from exc
        except GroqAPITimeoutError as exc:
            raise LLMRuntimeError("timeout_error", "Groq request timed out") from exc
        except GroqAPIConnectionError as exc:
            raise LLMRuntimeError("timeout_error", "Groq network request failed") from exc
        except GroqAPIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMRuntimeError("provider_error", "Groq provider error", retryable=True) from exc
            raise LLMRuntimeError("provider_error", f"Groq request failed with status {exc.status_code}") from exc

    async def _openai_response(
        self,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        system, chat_messages = _normalize_messages(messages, runtime_settings.prompt_override)
        payload: dict[str, Any] = {
            "model": runtime_settings.model,
            "input": [{"role": msg["role"], "content": msg["content"]} for msg in chat_messages],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["instructions"] = system
        if json_schema:
            payload["text"] = {"format": {"type": "json_schema", **json_schema}}
        return await self._http_json_request(
            runtime_settings,
            provider="openai",
            url="https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            payload=payload,
            extract_text=_extract_openai_text,
        )

    async def _anthropic_message(
        self,
        runtime_settings: LLMRuntimeSettings,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        system, chat_messages = _normalize_messages(messages, runtime_settings.prompt_override)
        payload: dict[str, Any] = {
            "model": runtime_settings.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": msg["role"], "content": msg["content"]} for msg in chat_messages],
        }
        if system:
            payload["system"] = system
        return await self._http_json_request(
            runtime_settings,
            provider="anthropic",
            url="https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
            extract_text=_extract_anthropic_text,
        )

    async def _http_json_request(
        self,
        runtime_settings: LLMRuntimeSettings,
        *,
        provider: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        extract_text,
    ) -> LLMResult:
        try:
            async with httpx.AsyncClient(timeout=runtime_settings.timeout_seconds) as client:
                response = await client.post(url, headers={"Content-Type": "application/json", **headers}, json=payload)
            if response.status_code in {401, 403}:
                raise LLMRuntimeError("auth_error", f"{provider} authentication failed")
            if response.status_code == 429:
                raise LLMRuntimeError("rate_limit_error", f"{provider} rate limit exceeded")
            if response.status_code >= 500:
                raise LLMRuntimeError("provider_error", f"{provider} provider error", retryable=True)
            if response.status_code >= 400:
                raise LLMRuntimeError("provider_error", f"{provider} request failed with status {response.status_code}")
            data = response.json()
            return LLMResult(text=extract_text(data), model=runtime_settings.model, provider=provider, raw=data)
        except httpx.TimeoutException as exc:
            raise LLMRuntimeError("timeout_error", f"{provider} request timed out") from exc
        except httpx.NetworkError as exc:
            raise LLMRuntimeError("timeout_error", f"{provider} network request failed") from exc


def _extract_openai_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for content in data.get("content", []) or []:
        if isinstance(content, dict) and content.get("type") == "text":
            chunks.append(str(content.get("text") or ""))
    return "\n".join(chunks).strip()


runtime = LLMRuntime()
