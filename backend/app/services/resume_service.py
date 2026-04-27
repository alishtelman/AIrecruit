import io
import uuid
from pathlib import Path

import httpx
from fastapi import UploadFile, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.resume import Resume
from app.schemas.resume import ResumeUploadResponse

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_BYTES = settings.MAX_RESUME_SIZE_MB * 1024 * 1024


def _validate_file(file: UploadFile, content: bytes) -> str:
    """Validate content-type and size. Returns the file extension."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: PDF, DOCX.",
        )
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_RESUME_SIZE_MB} MB.",
        )
    return ALLOWED_CONTENT_TYPES[file.content_type]


def _extract_text_pdf(content: bytes) -> str:
    from pdfminer.high_level import extract_text as pdf_extract_text

    return pdf_extract_text(io.BytesIO(content)) or ""


def _extract_text_docx(content: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_text(content: bytes, extension: str) -> str:
    try:
        if extension == ".pdf":
            return _extract_text_pdf(content)
        return _extract_text_docx(content)
    except Exception:
        # Extraction failure is non-fatal — store empty text rather than reject the upload
        return ""


RAW_TEXT_MAX_CHARS = 100_000


def _save_file(content: bytes, extension: str) -> Path:
    storage = Path(settings.RESUME_STORAGE_DIR)
    storage.mkdir(parents=True, exist_ok=True)

    # Security: filename is purely uuid-based, no user input in path
    filename = f"{uuid.uuid4().hex}{extension}"
    path = storage / filename
    path.write_bytes(content)
    return path


async def _process_resume_with_resume_service(file: UploadFile, content: bytes) -> dict:
    base_url = settings.RESUME_SERVICE_URL.rstrip("/")
    files = {
        "file": (
            file.filename or "resume",
            content,
            file.content_type or "application/octet-stream",
        )
    }
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        response = await client.post("/v1/resumes", files=files)

    if response.is_success:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Resume service returned invalid payload.",
        )

    raise HTTPException(
        status_code=response.status_code,
        detail=_extract_resume_service_error_detail(response),
    )


def _extract_resume_service_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return response.text.strip() or f"Resume service failed with status {response.status_code}."


async def upload_resume(
    db: AsyncSession,
    file: UploadFile,
    candidate: Candidate,
) -> ResumeUploadResponse:
    content = await file.read()

    if settings.RESUME_SERVICE_URL:
        try:
            processed = await _process_resume_with_resume_service(file, content)
            raw_text = str(processed.get("raw_text") or "")[:RAW_TEXT_MAX_CHARS]
            file_path = Path(str(processed.get("path") or ""))
            file_size = int(processed.get("file_size") or len(content))
            if not str(file_path):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Resume service returned empty file path.",
                )
            if not raw_text:
                extension = _validate_file(file, content)
                raw_text = _extract_text(content, extension)[:RAW_TEXT_MAX_CHARS]
        except httpx.RequestError:
            extension = _validate_file(file, content)
            raw_text = _extract_text(content, extension)[:RAW_TEXT_MAX_CHARS]
            file_path = _save_file(content, extension)
            file_size = len(content)
    else:
        extension = _validate_file(file, content)
        raw_text = _extract_text(content, extension)[:RAW_TEXT_MAX_CHARS]
        file_path = _save_file(content, extension)
        file_size = len(content)

    # Deactivate previous resumes
    await db.execute(
        update(Resume)
        .where(Resume.candidate_id == candidate.id, Resume.is_active.is_(True))
        .values(is_active=False)
    )

    resume = Resume(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        file_name=file.filename or file_path.name,
        file_path=str(file_path),
        file_size=file_size,
        raw_text=raw_text if raw_text else None,
        parsed_json=None,
        is_active=True,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    return ResumeUploadResponse(
        resume_id=resume.id,
        file_name=resume.file_name,
        text_length=len(raw_text),
        is_active=resume.is_active,
    )
