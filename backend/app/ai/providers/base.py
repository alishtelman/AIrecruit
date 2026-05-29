from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderAttempt:
    model: str
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class ProviderChatCompletionResult:
    text: str
    requested_model: str
    actual_model_used: str
    request_tokens_estimate: int = 0
    response_tokens_estimate: int = 0
    provider_latency_ms: float = 0.0
    provider_attempts: list[dict[str, Any]] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    fallback_used: bool = False
    raw_response: Any | None = None


class ProviderChatError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or "provider_error"


class LLMProvider(ABC):
    name: str = "unknown"

    @property
    @abstractmethod
    def configured_model(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError
