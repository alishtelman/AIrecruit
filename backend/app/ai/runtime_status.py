from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any


_lock = Lock()

_runtime_identity: dict[str, Any] = {
    "provider": "disabled",
    "model": "disabled",
    "api_key_present": False,
    "mock_enabled": False,
}

_runtime_events: dict[str, Any] = {
    "last_error": None,
    "last_success": None,
}


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def set_runtime_identity(*, provider: str, model: str, api_key_present: bool, mock_enabled: bool) -> None:
    with _lock:
        _runtime_identity["provider"] = str(provider)
        _runtime_identity["model"] = str(model)
        _runtime_identity["api_key_present"] = bool(api_key_present)
        _runtime_identity["mock_enabled"] = bool(mock_enabled)


def record_ai_success(*, component: str, provider: str, model: str, note: str | None = None) -> None:
    payload: dict[str, Any] = {
        "at": _utc_now_iso(),
        "component": component,
        "provider": provider,
        "model": model,
    }
    if note:
        payload["note"] = note
    with _lock:
        _runtime_events["last_success"] = payload


def record_ai_error(*, component: str, provider: str, model: str, error: str) -> None:
    payload = {
        "at": _utc_now_iso(),
        "component": component,
        "provider": provider,
        "model": model,
        "error": error,
    }
    with _lock:
        _runtime_events["last_error"] = payload


def get_ai_runtime_status() -> dict[str, Any]:
    with _lock:
        return {
            "provider": _runtime_identity["provider"],
            "model": _runtime_identity["model"],
            "mock_enabled": _runtime_identity["mock_enabled"],
            "api_key_present": _runtime_identity["api_key_present"],
            "last_error": _runtime_events["last_error"],
            "last_success": _runtime_events["last_success"],
        }
