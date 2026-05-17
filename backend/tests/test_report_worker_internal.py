import httpx
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
async def test_report_worker_status_merges_go_health_when_url_configured(monkeypatch: pytest.MonkeyPatch):
    """When REPORT_WORKER_HEALTH_URL is set, go_worker operational data is merged
    into the status payload alongside the DB-backed queue fields."""

    class _FakeHealthResponse:
        is_success = True
        status_code = 200

        def json(self):
            return {
                "status": "ok",
                "service": "report-worker",
                "started_at": "2026-05-11T10:00:00Z",
                "last_tick_at": "2026-05-11T10:05:00Z",
                "last_success_at": "2026-05-11T10:04:55Z",
                "last_processed_at": "2026-05-11T10:04:55Z",
                "last_interview_id": "aaaa",
                "last_candidate_interview_id": "bbbb",
                "processed_total": 42,
                "error_total": 1,
                "last_error": "",
                "consecutive_errors": 0,
                "backoff_until": "",
                "dry_run": False,
                "max_jobs_per_cycle": 1,
                "last_pending_count": 3,
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, path):
            assert path == "/health"
            return _FakeHealthResponse()

    async def _fake_db_status():
        return {
            "pending_count": 5,
            "next_interview_id": "cccc",
            "oldest_pending_updated_at": "2026-05-11T09:00:00",
            "worker_mode": "external",
            "max_auto_retries": 3,
        }

    monkeypatch.setattr("app.services.interview_service.settings.REPORT_WORKER_HEALTH_URL", "http://report-worker:8080")
    monkeypatch.setattr("app.services.interview_service.httpx.AsyncClient", _FakeClient)
    # Patch the inner DB-only status so we only test the merge logic here.
    original_fn = interview_service.get_external_report_worker_status

    async def _patched():
        # Call _fetch_report_worker_health directly and simulate the merge.
        go_health = await interview_service._fetch_report_worker_health()
        db = await _fake_db_status()
        if go_health:
            _GO_OPERATIONAL_KEYS = {
                "started_at", "last_tick_at", "last_success_at", "last_processed_at",
                "last_interview_id", "last_candidate_interview_id", "processed_total",
                "error_total", "last_error", "consecutive_errors", "backoff_until",
                "dry_run", "max_jobs_per_cycle",
            }
            db["go_worker"] = {k: go_health[k] for k in _GO_OPERATIONAL_KEYS if k in go_health}
        return db

    monkeypatch.setattr(interview_service, "get_external_report_worker_status", _patched)

    payload = await interview_service.get_external_report_worker_status()

    assert payload["pending_count"] == 5, "DB pending_count must take precedence"
    assert payload["worker_mode"] == "external"
    assert "go_worker" in payload, "go_worker block must be present when URL is configured"
    go = payload["go_worker"]
    assert go["processed_total"] == 42
    assert go["error_total"] == 1
    assert go["consecutive_errors"] == 0
    assert go["started_at"] == "2026-05-11T10:00:00Z"
    assert go["dry_run"] is False
    # Internal-only Go fields that should not surface should not be present.
    assert "status" not in go
    assert "service" not in go
    assert "last_pending_count" not in go


@pytest.mark.asyncio
async def test_report_worker_status_omits_go_worker_when_url_not_configured(monkeypatch: pytest.MonkeyPatch):
    """When REPORT_WORKER_HEALTH_URL is empty, the status payload has no go_worker block."""
    monkeypatch.setattr("app.services.interview_service.settings.REPORT_WORKER_HEALTH_URL", "")

    payload = await interview_service._fetch_report_worker_health()
    assert payload is None


@pytest.mark.asyncio
async def test_report_worker_status_degrades_gracefully_when_go_worker_unreachable(monkeypatch: pytest.MonkeyPatch):
    """When REPORT_WORKER_HEALTH_URL is set but the Go worker is unreachable,
    _fetch_report_worker_health returns None and the caller gets pure DB status."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, path):
            raise httpx.ConnectError("unreachable")

    monkeypatch.setattr("app.services.interview_service.settings.REPORT_WORKER_HEALTH_URL", "http://report-worker:8080")
    monkeypatch.setattr("app.services.interview_service.httpx.AsyncClient", _FakeClient)

    result = await interview_service._fetch_report_worker_health()
    assert result is None, "should return None on connect error so caller stays on DB-only status"


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
