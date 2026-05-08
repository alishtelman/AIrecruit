import httpx
import pytest

from app.services import platform_settings_service


def test_provider_key_status_prefers_llm_service_status(monkeypatch):
    monkeypatch.setattr("app.services.platform_settings_service.settings.GROQ_API_KEY", "")

    available, required_key = platform_settings_service._resolve_provider_key_status(
        "groq",
        {"groq": {"configured": True, "required_api_key": "GROQ_API_KEY"}},
    )

    assert available is True
    assert required_key == "GROQ_API_KEY"


def test_provider_key_status_falls_back_to_local_env(monkeypatch):
    monkeypatch.setattr("app.services.platform_settings_service.settings.OPENAI_API_KEY", "openai-key")

    available, required_key = platform_settings_service._resolve_provider_key_status("openai", None)

    assert available is True
    assert required_key == "OPENAI_API_KEY"


@pytest.mark.asyncio
async def test_llm_service_provider_statuses_parse_safe_payload(monkeypatch):
    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "service": "llm-service",
                "providers": [
                    {"provider": "groq", "required_api_key": "GROQ_API_KEY", "configured": True},
                    {"provider": "openrouter", "required_api_key": "OPENROUTER_API_KEY", "configured": False},
                    {"provider": "unknown", "required_api_key": "SECRET", "configured": True},
                ],
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):  # noqa: ANN001
            assert url == "http://llm-service:8080/v1/status"
            assert self.timeout == 1.0
            return _FakeResponse()

    monkeypatch.setattr("app.services.platform_settings_service.settings.LLM_SERVICE_URL", "http://llm-service:8080/")
    monkeypatch.setattr("app.services.platform_settings_service.httpx.AsyncClient", _FakeClient)

    statuses = await platform_settings_service._llm_service_provider_statuses()

    assert statuses == {
        "groq": {"configured": True, "required_api_key": "GROQ_API_KEY"},
        "openrouter": {"configured": False, "required_api_key": "OPENROUTER_API_KEY"},
    }


@pytest.mark.asyncio
async def test_llm_service_provider_statuses_falls_back_on_http_error(monkeypatch):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):  # noqa: ANN001
            raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("app.services.platform_settings_service.settings.LLM_SERVICE_URL", "http://llm-service:8080")
    monkeypatch.setattr("app.services.platform_settings_service.httpx.AsyncClient", _FakeClient)

    assert await platform_settings_service._llm_service_provider_statuses() is None
