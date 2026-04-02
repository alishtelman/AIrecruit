from types import SimpleNamespace

import pytest

from app.ai import interviewer as interviewer_mod
from app.ai.interviewer import InterviewContext, LLMInterviewer, _question_is_repeated


class _NoCallCompletions:
    async def create(self, **_: object) -> object:  # pragma: no cover - defensive branch
        raise AssertionError("LLM call must not happen for deterministic fallback path")


class _NoCallClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_NoCallCompletions())


class _StubCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    async def create(self, **_: object) -> object:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _StubClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_StubCompletions(content))


def test_question_repeat_detection_catches_semantic_duplication():
    history = [
        {
            "role": "assistant",
            "content": "How did you optimize PostgreSQL query plans in production?",
        }
    ]

    assert _question_is_repeated(
        "How did you optimize PostgreSQL query plans in production for latency?",
        history,
    )
    assert not _question_is_repeated(
        "How did you handle auth validation and safe degradation in backend services?",
        history,
    )


@pytest.mark.asyncio
async def test_get_next_question_switches_to_secondary_competency_when_primary_repeats():
    repeated_primary = "How did you design schema and optimize PostgreSQL or another database under real production load?"
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=3,
        language="en",
        competency_targets=[
            "Database Design & Optimization",
            "Security & Error Handling",
        ],
        message_history=[{"role": "assistant", "content": repeated_primary}],
        question_type="main",
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    assert "security" in question.lower() or "auth" in question.lower()
    assert question != repeated_primary


@pytest.mark.asyncio
async def test_get_next_question_uses_followup_fallback_when_llm_repeats(monkeypatch: pytest.MonkeyPatch):
    fallback_question = "Can you give a concrete example from your work?"
    monkeypatch.setattr(
        interviewer_mod,
        "get_fallback_followup",
        lambda _reason, _language="ru": fallback_question,
    )

    repeated = "Can you give me one concrete production example?"
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=4,
        language="en",
        question_type="followup",
        shallow_reason="no_depth_indicators",
        message_history=[
            {"role": "assistant", "content": repeated},
            {"role": "candidate", "content": "It depends on context."},
        ],
    )

    question = await LLMInterviewer(_StubClient(repeated)).get_next_question(ctx)

    assert question == fallback_question
