import pytest

from app.ai.runtime import LLMResult, LLMRuntime, LLMRuntimeError, LLMRuntimeSettings, runtime


@pytest.mark.asyncio
async def test_runtime_missing_api_key_is_configuration_error(monkeypatch):
    monkeypatch.setattr("app.ai.runtime.settings.OPENAI_API_KEY", "")
    with pytest.raises(LLMRuntimeError) as exc:
        await runtime.complete_text(
            runtime_settings=LLMRuntimeSettings(provider="openai", model="gpt-4.1-mini"),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=8,
            temperature=0,
        )
    assert exc.value.category == "configuration_error"
    assert "OPENAI_API_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_runtime_missing_openrouter_key_is_configuration_error(monkeypatch):
    monkeypatch.setattr("app.ai.runtime.settings.OPENROUTER_API_KEY", "")
    with pytest.raises(LLMRuntimeError) as exc:
        await runtime.complete_text(
            runtime_settings=LLMRuntimeSettings(provider="openrouter", model="openrouter/free"),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=8,
            temperature=0,
        )
    assert exc.value.category == "configuration_error"
    assert "OPENROUTER_API_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_openrouter_adapter_uses_chat_completions(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "openrouter ok"}}]}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):  # noqa: A002, ANN001
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr("app.ai.runtime.settings.OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr("app.ai.runtime.settings.LLM_SERVICE_URL", "")
    monkeypatch.setattr("app.ai.runtime.httpx.AsyncClient", _FakeClient)

    result = await runtime.complete_text(
        runtime_settings=LLMRuntimeSettings(provider="openrouter", model="openrouter/free", timeout_seconds=17),
        messages=[{"role": "system", "content": "system prompt"}, {"role": "user", "content": "hello"}],
        max_tokens=8,
        temperature=0,
    )

    assert result.text == "openrouter ok"
    assert result.provider == "openrouter"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["timeout"] == 17
    assert captured["headers"]["Authorization"] == "Bearer or-key"
    assert captured["payload"]["model"] == "openrouter/free"
    assert captured["payload"]["provider"] == {"allow_fallbacks": False}
    assert captured["payload"]["messages"][0] == {"role": "system", "content": "system prompt"}


@pytest.mark.asyncio
async def test_runtime_uses_llm_service_when_configured(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"text": "proxied ok", "model": "llama-3.3-70b-versatile", "provider": "groq"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json):  # noqa: A002, ANN001
            captured["url"] = url
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr("app.ai.runtime.settings.GROQ_API_KEY", "groq-key")
    monkeypatch.setattr("app.ai.runtime.settings.LLM_SERVICE_URL", "http://llm-service:8080")
    monkeypatch.setattr("app.ai.runtime.httpx.AsyncClient", _FakeClient)

    result = await runtime.complete_text(
        runtime_settings=LLMRuntimeSettings(
            provider="groq",
            model="llama-3.3-70b-versatile",
            timeout_seconds=11,
            max_retries=3,
        ),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=8,
        temperature=0,
    )

    assert result.text == "proxied ok"
    assert captured["url"] == "http://llm-service:8080/v1/complete"
    assert captured["timeout"] == 12
    assert captured["payload"]["provider"] == "groq"
    assert captured["payload"]["timeout_seconds"] == 11
    assert captured["payload"]["max_retries"] == 3


@pytest.mark.asyncio
async def test_runtime_maps_llm_service_errors(monkeypatch):
    class _FakeResponse:
        status_code = 503

        def json(self):
            return {"category": "configuration_error", "detail": "OPENAI_API_KEY is not configured"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json):  # noqa: A002, ANN001
            return _FakeResponse()

    monkeypatch.setattr("app.ai.runtime.settings.OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr("app.ai.runtime.settings.LLM_SERVICE_URL", "http://llm-service:8080")
    monkeypatch.setattr("app.ai.runtime.httpx.AsyncClient", _FakeClient)

    with pytest.raises(LLMRuntimeError) as exc:
        await runtime.complete_text(
            runtime_settings=LLMRuntimeSettings(provider="openai", model="gpt-4.1-mini"),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=8,
            temperature=0,
        )

    assert exc.value.category == "configuration_error"
    assert "OPENAI_API_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_runtime_retries_safe_transient_errors():
    class FlakyRuntime(LLMRuntime):
        def __init__(self) -> None:
            self.calls = 0

        def _validate_runtime(self, runtime_settings):  # noqa: ANN001
            return None

        async def _complete_text_once(self, **kwargs):  # noqa: ANN003
            self.calls += 1
            if self.calls == 1:
                raise LLMRuntimeError("timeout_error", "temporary timeout")
            return LLMResult(text="ok", model="test-model", provider="groq")

    flaky = FlakyRuntime()
    result = await flaky.complete_text(
        runtime_settings=LLMRuntimeSettings(provider="groq", model="llama-3.3-70b-versatile", max_retries=1),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=8,
        temperature=0,
    )
    assert result.text == "ok"
    assert flaky.calls == 2
