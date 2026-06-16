import uuid
from types import SimpleNamespace

from app.services.interview_service import _apply_voice_answer_metadata


def _interview() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
        target_role="product_manager",
        status="in_progress",
        interview_state={},
    )


def test_voice_answer_metadata_marks_confirmed_transcript_and_high_reliability():
    interview = _interview()

    _apply_voice_answer_metadata(
        interview,
        answer="Я проверил метрики, связался с бизнесом и приоритизировал hotfix.",
        input_mode="voice",
        transcript_confirmed=True,
        transcript_quality="good",
        audio_available=True,
        audio_duration_ms=8200,
        audio_size_bytes=32000,
    )

    state = interview.interview_state
    assert state["interview_mode"] == "voice"
    assert state["voice_metrics"]["total_answers"] == 1
    assert state["voice_metrics"]["voice_answers"] == 1
    assert state["voice_metrics"]["confirmed_transcripts"] == 1
    assert state["signal_reliability"]["level"] == "high"
    assert state["voice_turns"][0]["transcript_quality"] == "good"


def test_low_quality_voice_transcripts_reduce_signal_reliability():
    interview = _interview()

    for answer in ("не знаю", "да", "может быть"):
        _apply_voice_answer_metadata(
            interview,
            answer=answer,
            input_mode="voice",
            transcript_confirmed=True,
            transcript_quality="low",
            audio_available=False,
            audio_duration_ms=900,
            audio_size_bytes=900,
        )

    state = interview.interview_state
    assert state["voice_metrics"]["voice_answers"] == 3
    assert state["voice_metrics"]["low_quality_transcripts"] == 3
    assert state["voice_metrics"]["missing_audio_answers"] == 3
    assert state["signal_reliability"]["level"] == "low"


def test_text_fallback_is_tracked_without_breaking_voice_mode():
    interview = _interview()
    interview.interview_state = {"interview_mode": "voice"}

    _apply_voice_answer_metadata(
        interview,
        answer="Отвечаю текстом, потому что микрофон недоступен.",
        input_mode="text",
        transcript_confirmed=None,
        transcript_quality=None,
        audio_available=None,
        audio_duration_ms=None,
        audio_size_bytes=None,
    )

    state = interview.interview_state
    assert state["interview_mode"] == "voice"
    assert state["voice_metrics"]["total_answers"] == 1
    assert state["voice_metrics"]["text_fallback_answers"] == 1
