import pytest
from fastapi import HTTPException

from app.api.v1 import internal
from app.api.v1.internal import _verify_worker_token
from app.core.config import settings
from app.services import interview_service


def test_verify_worker_token_accepts_configured_token():
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = "secret"
    try:
        _verify_worker_token("secret")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token


def test_verify_worker_token_rejects_invalid_token():
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = "secret"
    try:
        with pytest.raises(HTTPException) as exc_info:
            _verify_worker_token("wrong")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token

    assert exc_info.value.status_code == 403


def test_verify_worker_token_requires_configured_token():
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = ""
    try:
        with pytest.raises(HTTPException) as exc_info:
            _verify_worker_token("secret")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_report_worker_tick_passes_dry_run(monkeypatch: pytest.MonkeyPatch):
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = "secret"
    captured = {}

    async def _fake_tick(*, dry_run: bool = False):
        captured["dry_run"] = dry_run
        return {"processed": False, "interview_id": "candidate", "dry_run": dry_run}

    monkeypatch.setattr(internal, "run_next_external_report_generation_job", _fake_tick)
    try:
        payload = await internal.run_report_worker_tick(
            dry_run=True,
            x_internal_worker_token="secret",
        )
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token

    assert captured["dry_run"] is True
    assert payload["processed"] is False
    assert payload["interview_id"] == "candidate"


@pytest.mark.asyncio
async def test_report_worker_status_requires_token_and_returns_safe_payload(monkeypatch: pytest.MonkeyPatch):
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = "secret"

    async def _fake_status():
        return {
            "pending_count": 2,
            "next_interview_id": "next-id",
            "oldest_pending_updated_at": "2026-05-08T00:00:00",
            "worker_mode": "embedded",
            "max_auto_retries": 3,
        }

    monkeypatch.setattr(internal, "get_external_report_worker_status", _fake_status)
    try:
        payload = await internal.get_report_worker_status(x_internal_worker_token="secret")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token

    assert payload == {
        "pending_count": 2,
        "next_interview_id": "next-id",
        "oldest_pending_updated_at": "2026-05-08T00:00:00",
        "worker_mode": "embedded",
        "max_auto_retries": 3,
    }
    assert "token" not in str(payload).lower()
    assert "secret" not in str(payload).lower()


@pytest.mark.asyncio
async def test_report_worker_dry_run_does_not_generate(monkeypatch: pytest.MonkeyPatch):
    async def _fake_status():
        return {
            "pending_count": 1,
            "next_interview_id": "11111111-1111-1111-1111-111111111111",
            "oldest_pending_updated_at": "2026-05-08T00:00:00",
            "worker_mode": "external",
            "max_auto_retries": 3,
        }

    async def _unexpected_generation(interview_id):
        raise AssertionError("dry-run must not generate reports")

    monkeypatch.setattr(interview_service, "get_external_report_worker_status", _fake_status)
    monkeypatch.setattr(interview_service, "_run_report_generation_job", _unexpected_generation)

    payload = await interview_service.run_next_external_report_generation_job(dry_run=True)

    assert payload["processed"] is False
    assert payload["dry_run"] is True
    assert payload["interview_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["pending_count"] == 1


@pytest.mark.asyncio
async def test_report_worker_tick_generates_without_dry_run(monkeypatch: pytest.MonkeyPatch):
    called = {}

    async def _fake_status():
        return {
            "pending_count": 1,
            "next_interview_id": "11111111-1111-1111-1111-111111111111",
            "oldest_pending_updated_at": "2026-05-08T00:00:00",
            "worker_mode": "external",
            "max_auto_retries": 3,
        }

    async def _fake_generation(interview_id):
        called["interview_id"] = str(interview_id)

    monkeypatch.setattr(interview_service, "get_external_report_worker_status", _fake_status)
    monkeypatch.setattr(interview_service, "_run_report_generation_job", _fake_generation)

    payload = await interview_service.run_next_external_report_generation_job(dry_run=False)

    assert payload["processed"] is True
    assert payload["dry_run"] is False
    assert called["interview_id"] == "11111111-1111-1111-1111-111111111111"
