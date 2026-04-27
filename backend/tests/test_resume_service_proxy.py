import uuid

import httpx
import pytest

import app.models.user  # noqa: F401 - ensure SQLAlchemy relationship targets are registered
from app.core.config import settings
from app.services.resume_service import (
    _process_resume_with_resume_service,
    upload_resume,
)


class _FakeUploadFile:
    filename = "resume.docx"
    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def __init__(self, content: bytes = b"docx") -> None:
        self._content = content

    async def read(self) -> bytes:
        return self._content


class _FakeDB:
    def __init__(self) -> None:
        self.added = None
        self.committed = False

    async def execute(self, *args, **kwargs) -> None:
        return None

    def add(self, value) -> None:
        self.added = value

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, value) -> None:
        return None


def _fake_candidate():
    return type("Candidate", (), {"id": uuid.uuid4()})()


@pytest.mark.asyncio
async def test_process_resume_with_resume_service_maps_payload(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.RESUME_SERVICE_URL
    settings.RESUME_SERVICE_URL = "http://resume-service:8080"

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, path: str, files: dict) -> httpx.Response:
            assert path == "/v1/resumes"
            filename, content, content_type = files["file"]
            assert filename == "resume.docx"
            assert content == b"docx"
            assert content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            return httpx.Response(
                200,
                json={
                    "path": "/app/storage/resumes/abc.docx",
                    "file_size": 4,
                    "raw_text": "Senior backend engineer",
                },
            )

    monkeypatch.setattr("app.services.resume_service.httpx.AsyncClient", _FakeClient)
    try:
        payload = await _process_resume_with_resume_service(_FakeUploadFile(), b"docx")
    finally:
        settings.RESUME_SERVICE_URL = original_url

    assert payload["path"] == "/app/storage/resumes/abc.docx"
    assert payload["raw_text"] == "Senior backend engineer"


@pytest.mark.asyncio
async def test_upload_resume_uses_resume_service(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.RESUME_SERVICE_URL
    settings.RESUME_SERVICE_URL = "http://resume-service:8080"
    db = _FakeDB()

    async def _fake_process(file, content: bytes) -> dict:
        return {
            "path": "/app/storage/resumes/abc.docx",
            "file_size": len(content),
            "raw_text": "Go Python SQL",
        }

    monkeypatch.setattr("app.services.resume_service._process_resume_with_resume_service", _fake_process)
    try:
        response = await upload_resume(db, _FakeUploadFile(b"content"), _fake_candidate())
    finally:
        settings.RESUME_SERVICE_URL = original_url

    assert response.text_length == len("Go Python SQL")
    assert db.added.file_path == "/app/storage/resumes/abc.docx"
    assert db.added.raw_text == "Go Python SQL"
    assert db.committed is True


@pytest.mark.asyncio
async def test_upload_resume_falls_back_when_resume_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    original_url = settings.RESUME_SERVICE_URL
    original_storage = settings.RESUME_STORAGE_DIR
    settings.RESUME_SERVICE_URL = "http://resume-service:8080"
    settings.RESUME_STORAGE_DIR = str(tmp_path)
    db = _FakeDB()

    async def _failing_process(file, content: bytes) -> dict:
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("app.services.resume_service._process_resume_with_resume_service", _failing_process)
    monkeypatch.setattr("app.services.resume_service._extract_text", lambda content, extension: "local text")
    try:
        response = await upload_resume(db, _FakeUploadFile(b"content"), _fake_candidate())
    finally:
        settings.RESUME_SERVICE_URL = original_url
        settings.RESUME_STORAGE_DIR = original_storage

    assert response.text_length == len("local text")
    assert db.added.raw_text == "local text"
    assert db.added.file_path.startswith(str(tmp_path))


@pytest.mark.asyncio
async def test_upload_resume_uses_local_extraction_when_resume_service_text_is_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    original_url = settings.RESUME_SERVICE_URL
    settings.RESUME_SERVICE_URL = "http://resume-service:8080"
    db = _FakeDB()

    async def _fake_process(file, content: bytes) -> dict:
        return {
            "path": "/app/storage/resumes/abc.docx",
            "file_size": len(content),
            "raw_text": "",
        }

    monkeypatch.setattr("app.services.resume_service._process_resume_with_resume_service", _fake_process)
    monkeypatch.setattr("app.services.resume_service._extract_text", lambda content, extension: "python text")
    try:
        response = await upload_resume(db, _FakeUploadFile(b"content"), _fake_candidate())
    finally:
        settings.RESUME_SERVICE_URL = original_url

    assert response.text_length == len("python text")
    assert db.added.file_path == "/app/storage/resumes/abc.docx"
    assert db.added.raw_text == "python text"
