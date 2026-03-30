from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import httpx
from groq import AsyncGroq

from app.core.config import settings

_DEFAULT_LANGUAGE = "en"
_MAX_TOTAL_CHARS = 4000

_GROQ_SUPPORTED_LANGUAGES = {"en"}
_GROQ_MODEL = "canopylabs/orpheus-v1-english"
_GROQ_VOICE = "hannah"
_GROQ_MAX_SEGMENT_CHARS = 200

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
_ELEVENLABS_DEFAULT_MODEL = "eleven_flash_v2_5"
_ELEVENLABS_DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
_ELEVENLABS_TIMEOUT_SECONDS = 30.0


class TTSServiceError(Exception):
    """Base exception for TTS provider failures."""


class TTSUnsupportedLanguageError(TTSServiceError):
    """Raised when a provider cannot synthesize the requested language."""


class TTSUnavailableError(TTSServiceError):
    """Raised when a provider is temporarily unavailable or not configured."""


class TTSConfigurationError(TTSUnavailableError):
    """Raised when a provider cannot be used due to missing configuration."""


class TTSProviderError(TTSServiceError):
    """Raised when an upstream provider returns an unexpected failure."""


@dataclass
class TTSResult:
    audio_bytes: bytes
    media_type: str
    provider: str
    model: str


class BaseTTSProvider:
    name: str

    async def synthesize(self, text: str, language: str) -> TTSResult:  # pragma: no cover - interface
        raise NotImplementedError


def normalize_tts_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise ValueError("text cannot be empty")
    return normalized[:_MAX_TOTAL_CHARS]


def normalize_tts_language(language: str | None) -> str:
    normalized = (language or _DEFAULT_LANGUAGE).strip().lower()
    return normalized or _DEFAULT_LANGUAGE


def _chunk_text(text: str, max_chars: int = _GROQ_MAX_SEGMENT_CHARS) -> list[str]:
    """Split long text into Groq-safe segments, preferring sentence boundaries."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    split_chars = ".!?;:, "
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining.strip())
            break

        window = remaining[:max_chars]
        split_at = max(window.rfind(ch) for ch in split_chars)
        if split_at <= 0:
            split_at = max_chars

        chunk = remaining[:split_at].strip()
        if not chunk:
            chunk = remaining[:max_chars].strip()
            split_at = len(chunk)

        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    return chunks


def _merge_wav_chunks(chunks: list[bytes]) -> bytes:
    """Concatenate same-format WAV chunks into a single WAV file."""
    if not chunks:
        raise ValueError("no audio chunks to merge")
    if len(chunks) == 1:
        return chunks[0]

    output = io.BytesIO()
    params = None
    with wave.open(output, "wb") as writer:
        for chunk in chunks:
            with wave.open(io.BytesIO(chunk), "rb") as reader:
                current_params = reader.getparams()
                if params is None:
                    params = current_params
                    writer.setparams(current_params)
                elif (
                    current_params.nchannels != params.nchannels
                    or current_params.sampwidth != params.sampwidth
                    or current_params.framerate != params.framerate
                    or current_params.comptype != params.comptype
                    or current_params.compname != params.compname
                ):
                    raise ValueError("incompatible TTS audio chunk parameters")
                writer.writeframes(reader.readframes(reader.getnframes()))
    return output.getvalue()


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


class GroqTTSProvider(BaseTTSProvider):
    name = "groq"

    async def synthesize(self, text: str, language: str) -> TTSResult:
        if not settings.GROQ_API_KEY:
            raise TTSConfigurationError("Groq TTS not configured (no GROQ_API_KEY)")
        if language not in _GROQ_SUPPORTED_LANGUAGES:
            raise TTSUnsupportedLanguageError(f"Groq TTS does not support language '{language}'")

        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        try:
            audio_chunks: list[bytes] = []
            for chunk in _chunk_text(text):
                audio_response = await client.audio.speech.create(
                    model=_GROQ_MODEL,
                    voice=_GROQ_VOICE,
                    input=chunk,
                    response_format="wav",
                )
                audio_chunks.append(audio_response.read())
            audio_bytes = _merge_wav_chunks(audio_chunks)
        except ValueError as exc:
            raise TTSProviderError(str(exc)) from exc
        except Exception as exc:
            raise TTSProviderError(f"Groq TTS generation failed: {exc}") from exc

        return TTSResult(
            audio_bytes=audio_bytes,
            media_type="audio/wav",
            provider=self.name,
            model=_GROQ_MODEL,
        )


class ElevenLabsTTSProvider(BaseTTSProvider):
    name = "elevenlabs"

    async def synthesize(self, text: str, language: str) -> TTSResult:
        if not settings.ELEVENLABS_API_KEY:
            raise TTSConfigurationError("ElevenLabs TTS not configured (no ELEVENLABS_API_KEY)")

        voice_id = settings.ELEVENLABS_VOICE_ID or _ELEVENLABS_DEFAULT_VOICE_ID
        model = settings.ELEVENLABS_TTS_MODEL or _ELEVENLABS_DEFAULT_MODEL
        payload = {
            "text": text,
            "model_id": model,
        }

        async with httpx.AsyncClient(
            base_url=_ELEVENLABS_API_BASE,
            timeout=_ELEVENLABS_TIMEOUT_SECONDS,
        ) as client:
            try:
                response = await client.post(
                    f"/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": settings.ELEVENLABS_API_KEY,
                        "Accept": "audio/mpeg",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                raise TTSUnavailableError("ElevenLabs TTS timed out") from exc
            except httpx.HTTPError as exc:
                raise TTSUnavailableError(f"ElevenLabs TTS request failed: {exc}") from exc

        if response.is_success:
            media_type = response.headers.get("content-type", "audio/mpeg").split(";")[0] or "audio/mpeg"
            return TTSResult(
                audio_bytes=response.content,
                media_type=media_type,
                provider=self.name,
                model=model,
            )

        detail = _extract_error_detail(response)
        lowered = detail.lower()
        if response.status_code in {429, 500, 502, 503, 504}:
            raise TTSUnavailableError(f"ElevenLabs TTS unavailable: {detail}")
        if response.status_code in {400, 404, 422} and "language" in lowered:
            raise TTSUnsupportedLanguageError(detail)
        if response.status_code in {401, 403}:
            raise TTSUnavailableError(f"ElevenLabs TTS authentication failed: {detail}")
        raise TTSProviderError(f"ElevenLabs TTS failed: {detail}")


def _provider_chain(primary: str, fallback: str) -> list[str]:
    chain: list[str] = []
    for name in (primary, fallback):
        normalized = name.strip().lower()
        if normalized and normalized not in chain:
            chain.append(normalized)
    return chain


def _provider_map() -> dict[str, BaseTTSProvider]:
    return {
        "groq": GroqTTSProvider(),
        "elevenlabs": ElevenLabsTTSProvider(),
    }


def _finalize_provider_error(errors: list[TTSServiceError]) -> TTSServiceError:
    for error in errors:
        if isinstance(error, TTSProviderError):
            return error
    for error in errors:
        if isinstance(error, TTSUnsupportedLanguageError):
            return error
    for error in errors:
        if isinstance(error, TTSUnavailableError) and not isinstance(error, TTSConfigurationError):
            return error
    for error in errors:
        if isinstance(error, TTSConfigurationError):
            return error
    return errors[-1] if errors else TTSUnavailableError("No TTS providers available")


async def _synthesize_with_provider_chain(
    text: str,
    language: str,
    provider_names: list[str],
    providers: dict[str, BaseTTSProvider],
) -> TTSResult:
    errors: list[TTSServiceError] = []

    for name in provider_names:
        provider = providers.get(name)
        if provider is None:
            errors.append(TTSConfigurationError(f"Unsupported TTS provider '{name}'"))
            continue
        try:
            return await provider.synthesize(text, language)
        except TTSServiceError as exc:
            errors.append(exc)

    raise _finalize_provider_error(errors)


async def synthesize_text_to_speech(text: str, language: str | None) -> TTSResult:
    normalized_text = normalize_tts_text(text)
    normalized_language = normalize_tts_language(language)
    return await _synthesize_with_provider_chain(
        normalized_text,
        normalized_language,
        _provider_chain(settings.TTS_PROVIDER, settings.TTS_FALLBACK_PROVIDER),
        _provider_map(),
    )
