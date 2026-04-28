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
