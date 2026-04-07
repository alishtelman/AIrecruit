import pytest

from app.core.config import Settings


def _strict_production_kwargs(**overrides):
    base = {
        "APP_ENV": "production",
        "SECRET_KEY": "x" * 40,
        "SESSION_COOKIE_SECURE": True,
        "AUTH_ALLOW_BEARER": False,
        "CORS_ORIGINS": "https://app.example.com",
        "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
    }
    base.update(overrides)
    return base


def test_production_rejects_bearer_enabled():
    cfg = Settings(**_strict_production_kwargs(AUTH_ALLOW_BEARER=True))
    with pytest.raises(ValueError, match="AUTH_ALLOW_BEARER"):
        cfg.validate_security_settings()


def test_production_rejects_insecure_session_cookie():
    cfg = Settings(**_strict_production_kwargs(SESSION_COOKIE_SECURE=False))
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        cfg.validate_security_settings()


def test_production_rejects_wildcard_cors():
    cfg = Settings(**_strict_production_kwargs(CORS_ORIGINS="*"))
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        cfg.validate_security_settings()


def test_production_rejects_wildcard_csrf_origins():
    cfg = Settings(**_strict_production_kwargs(CSRF_TRUSTED_ORIGINS="https://app.example.com,*"))
    with pytest.raises(ValueError, match="CSRF_TRUSTED_ORIGINS"):
        cfg.validate_security_settings()


def test_production_accepts_strict_configuration():
    cfg = Settings(**_strict_production_kwargs())
    cfg.validate_security_settings()
