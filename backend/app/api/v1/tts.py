"""
Text-to-Speech endpoint.

POST /api/v1/tts  — converts text to speech via the configured provider chain.
Requires authentication (candidate or company_admin).
Falls back to the configured backup provider if the primary TTS provider is unavailable.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.v1.deps import get_current_user
from app.models.user import User
from app.services.tts_service import (
    TTSProviderError,
    TTSUnavailableError,
    TTSUnsupportedLanguageError,
    synthesize_text_to_speech,
)

router = APIRouter(prefix="/tts", tags=["tts"])


class TTSRequest(BaseModel):
    text: str
    language: str | None = None


@router.post("", response_class=Response)
async def synthesize(
    body: TTSRequest,
    _user: User = Depends(get_current_user),
) -> Response:
    """Convert text to speech. Returns audio binary."""
    try:
        result = await synthesize_text_to_speech(body.text, body.language)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except TTSUnsupportedLanguageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except TTSUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except TTSProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return Response(
        content=result.audio_bytes,
        media_type=result.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-TTS-Provider": result.provider,
            "X-TTS-Model": result.model,
        },
    )
