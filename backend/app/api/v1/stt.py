"""
Speech-to-Text endpoint.

POST /api/v1/stt  — transcribes audio via Groq Whisper.
Accepts multipart/form-data with a single audio file field.
Returns {"text": "..."}.
Requires authentication.
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

import httpx

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.models.user import User

router = APIRouter(prefix="/stt", tags=["stt"])

_MODEL = "whisper-large-v3-turbo"
_MAX_BYTES = 25 * 1024 * 1024  # Groq Whisper limit: 25 MB


@router.post("")
async def transcribe(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
) -> dict:
    """Transcribe audio to text. Returns {text: str}."""
    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio file")
    if len(audio_bytes) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file too large (max 25 MB)",
        )

    if settings.MEDIA_SERVICE_URL:
        try:
            return await _transcribe_with_media_service(file, audio_bytes)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Media service request failed: {exc}",
            )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="STT is handled by media sidecar, but MEDIA_SERVICE_URL is not set.",
    )


async def _transcribe_with_media_service(file: UploadFile, audio_bytes: bytes) -> dict:
    base_url = settings.MEDIA_SERVICE_URL.rstrip("/")
    filename = file.filename or "audio.webm"
    content_type = file.content_type or "audio/webm"
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        response = await client.post(
            "/v1/stt",
            files={"file": (filename, audio_bytes, content_type)},
        )

    if response.is_success:
        return response.json()

    detail = _extract_error_detail(response)
    raise HTTPException(status_code=response.status_code, detail=detail)


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    body = response.text.strip()
    return body or f"HTTP {response.status_code}"
