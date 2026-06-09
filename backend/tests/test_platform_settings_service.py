from app.services import platform_settings_service


def test_provider_key_status_uses_openai_api_key(monkeypatch):
    monkeypatch.setattr("app.services.platform_settings_service.settings.OPENAI_API_KEY", "openai-key")

    available, required_key = platform_settings_service._resolve_provider_key_status("openai")
    assert available is True
    assert required_key == "OPENAI_API_KEY"


def test_provider_key_status_reports_missing_openai_api_key(monkeypatch):
    monkeypatch.setattr("app.services.platform_settings_service.settings.OPENAI_API_KEY", "")

    available, required_key = platform_settings_service._resolve_provider_key_status("openai")
    assert available is False
    assert required_key == "OPENAI_API_KEY"


def test_model_options_are_openai_only():
    assert platform_settings_service.model_options_payload() == {
        "openai": ["gpt-5.4-mini", "gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini"],
    }
