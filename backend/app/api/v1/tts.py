"""
Text-to-Speech endpoint.

POST /api/v1/tts  — converts text to speech via Groq PlayAI TTS.
Requires authentication (candidate or company_admin).
Falls back to 503 if GROQ_API_KEY is not set.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from groq import AsyncGroq

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.models.user import User

router = APIRouter(prefix="/tts", tags=["tts"])

# English-language voice; warm and clear for interview context
_VOICE = "Celeste-PlayAI"
_MODEL = "playai-tts"
_MAX_CHARS = 4000  # Groq TTS limit


class TTSRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text cannot be empty")
        return v[:_MAX_CHARS]


@router.post("", response_class=Response)
async def synthesize(
    body: TTSRequest,
    _user: User = Depends(get_current_user),
) -> Response:
    """Convert text to speech. Returns audio/mpeg binary."""
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS service not configured (no GROQ_API_KEY)",
        )

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        audio_response = await client.audio.speech.create(
            model=_MODEL,
            voice=_VOICE,
            input=body.text,
            response_format="mp3",
        )
        audio_bytes = audio_response.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TTS generation failed: {exc}",
        ) from exc

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )
