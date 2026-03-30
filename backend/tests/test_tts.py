from __future__ import annotations

import wave
from io import BytesIO

import pytest

from app.services.tts_service import (
    TTSConfigurationError,
    TTSProviderError,
    TTSResult,
    TTSUnavailableError,
    TTSUnsupportedLanguageError,
    _chunk_text,
    _merge_wav_chunks,
    _provider_chain,
    _synthesize_with_provider_chain,
)


def _wav_chunk(frame_count: int, frame_byte: bytes = b"\x01\x02") -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(frame_byte * frame_count)
    return buf.getvalue()


def test_chunk_text_preserves_full_content_with_sentence_boundaries():
    text = (
        "This is a long interview prompt that should be split cleanly. "
        "It includes multiple sentences so the chunking prefers natural pauses. "
        "The last sentence is here."
    )

    chunks = _chunk_text(text, max_chars=70)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 70 for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_merge_wav_chunks_combines_audio_frames():
    first = _wav_chunk(4, b"\x01\x00")
    second = _wav_chunk(6, b"\x02\x00")

    merged = _merge_wav_chunks([first, second])

    with wave.open(BytesIO(merged), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24000
        assert wav_file.getnframes() == 10


def test_merge_wav_chunks_requires_at_least_one_chunk():
    with pytest.raises(ValueError, match="no audio chunks"):
        _merge_wav_chunks([])


def test_provider_chain_deduplicates_fallback_name():
    assert _provider_chain("elevenlabs", "groq") == ["elevenlabs", "groq"]
    assert _provider_chain("groq", "groq") == ["groq"]


class _FakeProvider:
    def __init__(self, *, result: TTSResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str) -> TTSResult:
        self.calls.append((text, language))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.mark.asyncio
async def test_synthesize_prefers_primary_provider_when_available():
    eleven = _FakeProvider(
        result=TTSResult(b"eleven", "audio/mpeg", provider="elevenlabs", model="flash"),
    )
    groq = _FakeProvider(
        result=TTSResult(b"groq", "audio/wav", provider="groq", model="orpheus"),
    )

    result = await _synthesize_with_provider_chain(
        "hello world",
        "en",
        ["elevenlabs", "groq"],
        {"elevenlabs": eleven, "groq": groq},
    )

    assert result.provider == "elevenlabs"
    assert eleven.calls == [("hello world", "en")]
    assert groq.calls == []


@pytest.mark.asyncio
async def test_synthesize_falls_back_when_primary_provider_is_unavailable():
    eleven = _FakeProvider(error=TTSUnavailableError("credits exhausted"))
    groq = _FakeProvider(
        result=TTSResult(b"groq", "audio/wav", provider="groq", model="orpheus"),
    )

    result = await _synthesize_with_provider_chain(
        "fallback please",
        "en",
        ["elevenlabs", "groq"],
        {"elevenlabs": eleven, "groq": groq},
    )

    assert result.provider == "groq"
    assert eleven.calls == [("fallback please", "en")]
    assert groq.calls == [("fallback please", "en")]


@pytest.mark.asyncio
async def test_synthesize_falls_back_when_primary_provider_is_missing_configuration():
    eleven = _FakeProvider(error=TTSConfigurationError("missing ELEVENLABS_API_KEY"))
    groq = _FakeProvider(
        result=TTSResult(b"groq", "audio/wav", provider="groq", model="orpheus"),
    )

    result = await _synthesize_with_provider_chain(
        "hello world",
        "en",
        ["elevenlabs", "groq"],
        {"elevenlabs": eleven, "groq": groq},
    )

    assert result.provider == "groq"


@pytest.mark.asyncio
async def test_synthesize_returns_primary_provider_error_when_fallback_cannot_handle_language():
    eleven = _FakeProvider(error=TTSProviderError("ElevenLabs quota exceeded"))
    groq = _FakeProvider(error=TTSUnsupportedLanguageError("Groq does not support language 'ru'"))

    with pytest.raises(TTSProviderError, match="quota exceeded"):
        await _synthesize_with_provider_chain(
            "privet",
            "ru",
            ["elevenlabs", "groq"],
            {"elevenlabs": eleven, "groq": groq},
        )


@pytest.mark.asyncio
async def test_synthesize_returns_unsupported_language_when_only_available_provider_cannot_handle_it():
    eleven = _FakeProvider(error=TTSConfigurationError("missing ELEVENLABS_API_KEY"))
    groq = _FakeProvider(error=TTSUnsupportedLanguageError("Groq does not support language 'ru'"))

    with pytest.raises(TTSUnsupportedLanguageError, match="does not support language 'ru'"):
        await _synthesize_with_provider_chain(
            "privet",
            "ru",
            ["elevenlabs", "groq"],
            {"elevenlabs": eleven, "groq": groq},
        )
