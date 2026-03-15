import io
import uuid
from pathlib import Path

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


async def upload_resume(
    db: AsyncSession,
    file: UploadFile,
    candidate: Candidate,
) -> ResumeUploadResponse:
    content = await file.read()

    extension = _validate_file(file, content)
    raw_text = _extract_text(content, extension)[:RAW_TEXT_MAX_CHARS]
    file_path = _save_file(content, extension)

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
        file_size=len(content),
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
