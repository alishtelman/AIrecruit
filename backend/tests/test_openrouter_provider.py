import pytest

from app.ai.providers.base import ProviderChatError
from app.ai.providers.openrouter_provider import OpenRouterProvider


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_openrouter_provider_sets_required_headers(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        async def post(self, url: str, headers: dict, json: dict):
            seen["url"] = url
            seen["headers"] = headers
            seen["json"] = json
            return _FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr("app.ai.providers.openrouter_provider.httpx.AsyncClient", _FakeClient)

    provider = OpenRouterProvider(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        default_model="qwen/qwen3-235b-a22b:free",
        fallback_models=[],
        site_url="http://localhost:3000",
        app_name="AI Talent Verification Platform",
    )
    result = await provider.chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model=None,
        temperature=0.1,
        max_tokens=64,
    )

    assert result.text == "ok"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["headers"]["HTTP-Referer"] == "http://localhost:3000"
    assert seen["headers"]["X-Title"] == "AI Talent Verification Platform"
    assert seen["json"]["model"] == "qwen/qwen3-235b-a22b:free"


@pytest.mark.asyncio
async def test_openrouter_provider_reads_tool_call_arguments(monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        async def post(self, url: str, headers: dict, json: dict):
            _ = (url, headers, json)
            return _FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "submit",
                                            "arguments": "{\"ok\":true}",
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr("app.ai.providers.openrouter_provider.httpx.AsyncClient", _FakeClient)

    provider = OpenRouterProvider(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        default_model="model/one:free",
        fallback_models=[],
        site_url="http://localhost:3000",
        app_name="AI Talent Verification Platform",
    )
    result = await provider.chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model=None,
        temperature=0.1,
        max_tokens=64,
    )

    assert result.text == "{\"ok\":true}"


@pytest.mark.asyncio
async def test_openrouter_provider_tries_fallback_models(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        async def post(self, url: str, headers: dict, json: dict):
            _ = (url, headers)
            model = str(json.get("model") or "")
            calls.append(model)
            if model == "model/first:free":
                return _FakeResponse(
                    429,
                    {"error": {"code": "rate_limit", "message": "rate limited"}},
                )
            return _FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "second model answer",
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr("app.ai.providers.openrouter_provider.httpx.AsyncClient", _FakeClient)

    provider = OpenRouterProvider(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        default_model="model/first:free",
        fallback_models=["model/second:free"],
        site_url="http://localhost:3000",
        app_name="AI Talent Verification Platform",
    )
    result = await provider.chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model=None,
        temperature=0.1,
        max_tokens=64,
    )

    assert calls == ["model/first:free", "model/second:free"]
    assert result.actual_model_used == "model/second:free"
    assert result.fallback_used is True
    assert len(result.provider_attempts) == 2
    assert result.provider_attempts[0]["ok"] is False
    assert result.provider_attempts[1]["ok"] is True
    assert result.provider_errors


@pytest.mark.asyncio
async def test_openrouter_provider_fails_after_all_models(monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        async def post(self, url: str, headers: dict, json: dict):
            _ = (url, headers, json)
            return _FakeResponse(
                500,
                {"error": {"code": "provider_error", "message": "provider down"}},
            )

    monkeypatch.setattr("app.ai.providers.openrouter_provider.httpx.AsyncClient", _FakeClient)

    provider = OpenRouterProvider(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        default_model="model/a:free",
        fallback_models=["model/b:free"],
        site_url="http://localhost:3000",
        app_name="AI Talent Verification Platform",
    )

    with pytest.raises(ProviderChatError) as exc_info:
        await provider.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            temperature=0.1,
            max_tokens=64,
        )

    assert exc_info.value.code == "all_models_failed"
