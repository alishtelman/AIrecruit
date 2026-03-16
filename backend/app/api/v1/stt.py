"""
Speech-to-Text endpoint.

POST /api/v1/stt  — transcribes audio via Groq Whisper.
Accepts multipart/form-data with a single audio file field.
Returns {"text": "..."}.
Requires authentication.
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from groq import AsyncGroq

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
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STT service not configured (no GROQ_API_KEY)",
        )

    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio file")
    if len(audio_bytes) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file too large (max 25 MB)",
        )

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        filename = file.filename or "audio.webm"
        transcription = await client.audio.transcriptions.create(
            model=_MODEL,
            file=(filename, audio_bytes, file.content_type or "audio/webm"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Transcription failed: {exc}",
        ) from exc

    return {"text": transcription.text}
