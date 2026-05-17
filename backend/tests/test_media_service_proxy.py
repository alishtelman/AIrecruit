from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api.v1.stt import _transcribe_with_media_service
from app.core.config import settings
from app.services.interview_service import _save_recording_with_media_service


class _FakeUpload:
    def __init__(self, chunks: list[bytes], *, filename: str = "answer.webm", content_type: str = "audio/webm") -> None:
        self._chunks = list(chunks)
        self.filename = filename
        self.content_type = content_type

    async def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


@pytest.mark.asyncio
async def test_transcribe_with_media_service_returns_text(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.MEDIA_SERVICE_URL
    settings.MEDIA_SERVICE_URL = "http://media-service:8080"

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, path: str, files: dict) -> httpx.Response:
            assert path == "/v1/stt"
            filename, audio_bytes, content_type = files["file"]
            assert filename == "answer.webm"
            assert audio_bytes == b"audio"
            assert content_type == "audio/webm"
            return httpx.Response(200, json={"text": "transcribed answer"})

    monkeypatch.setattr("app.api.v1.stt.httpx.AsyncClient", _FakeClient)
    try:
        result = await _transcribe_with_media_service(
            SimpleNamespace(filename="answer.webm", content_type="audio/webm"),
            b"audio",
        )
    finally:
        settings.MEDIA_SERVICE_URL = original_url

    assert result == {"text": "transcribed answer"}


@pytest.mark.asyncio
async def test_transcribe_with_media_service_preserves_error_detail(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.MEDIA_SERVICE_URL
    settings.MEDIA_SERVICE_URL = "http://media-service:8080"

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, path: str, files: dict) -> httpx.Response:
            return httpx.Response(413, json={"detail": "too large"})

    monkeypatch.setattr("app.api.v1.stt.httpx.AsyncClient", _FakeClient)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await _transcribe_with_media_service(
                SimpleNamespace(filename="answer.webm", content_type="audio/webm"),
                b"audio",
            )
    finally:
        settings.MEDIA_SERVICE_URL = original_url

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "too large"


@pytest.mark.asyncio
async def test_save_recording_with_media_service_streams_upload(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.MEDIA_SERVICE_URL
    settings.MEDIA_SERVICE_URL = "http://media-service:8080"
    sent_chunks: list[bytes] = []

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, path: str, content, headers: dict) -> httpx.Response:
            assert path == "/v1/recordings/00000000-0000-0000-0000-000000000001"
            assert headers["Content-Type"] == "video/webm"
            async for chunk in content:
                sent_chunks.append(chunk)
            return httpx.Response(200, json={"path": "/app/storage/recordings/00000000-0000-0000-0000-000000000001.webm"})

    monkeypatch.setattr("app.services.interview_service.httpx.AsyncClient", _FakeClient)
    try:
        path = await _save_recording_with_media_service(
            "00000000-0000-0000-0000-000000000001",
            _FakeUpload([b"first", b"second"], content_type="video/webm"),
        )
    finally:
        settings.MEDIA_SERVICE_URL = original_url

    assert sent_chunks == [b"first", b"second"]
    assert path == "/app/storage/recordings/00000000-0000-0000-0000-000000000001.webm"


@pytest.mark.asyncio
async def test_save_recording_with_media_service_preserves_error_detail(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.MEDIA_SERVICE_URL
    settings.MEDIA_SERVICE_URL = "http://media-service:8080"

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, path: str, content, headers: dict) -> httpx.Response:
            return httpx.Response(415, json={"detail": "bad media type"})

    monkeypatch.setattr("app.services.interview_service.httpx.AsyncClient", _FakeClient)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await _save_recording_with_media_service(
                "00000000-0000-0000-0000-000000000001",
                _FakeUpload([b"recording"], content_type="text/plain"),
            )
    finally:
        settings.MEDIA_SERVICE_URL = original_url

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == "bad media type"
