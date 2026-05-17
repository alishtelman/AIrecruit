from types import SimpleNamespace

import pytest

from app.ai import interviewer as interviewer_mod
from app.ai.interviewer import (
    InterviewContext,
    _build_system_prompt,
    classify_answer,
    LLMInterviewer,
    _normalize_question_output,
    _question_is_repeated,
    _recent_candidate_requested_move_on,
)


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


def test_classify_answer_detects_honest_gap_for_manual_only_phrase():
    answer_class, reason = classify_answer("пока ничего, только мануалка и базовые проверки руками")

    assert answer_class == "no_experience_honest"
    assert reason in {"too_short", "no_depth_indicators"}


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
async def test_get_next_question_switches_when_current_topic_signature_already_covered():
    signature = "technical|technical_foundation|core|postgresql|test strategy planning"
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=5,
        language="ru",
        question_type="main",
        current_topic=signature,
        asked_topics=[signature],
        competency_targets=[
            "Test Strategy & Planning",
            "API & Performance Testing",
        ],
        message_history=[{"role": "assistant", "content": "Опишите, как вы строите test strategy для новой фичи."}],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert question.endswith("?")
    assert "test strategy" not in normalized
    assert "api" in normalized or "нагруз" in normalized or "производитель" in normalized


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


@pytest.mark.asyncio
async def test_get_next_question_reframes_honest_gap_without_llm_call():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=5,
        language="ru",
        question_type="followup",
        answer_class="no_experience_honest",
        shallow_reason="no_depth_indicators",
        message_history=[
            {"role": "assistant", "content": "Как вы автоматизировали flaky UI тесты?"},
            {"role": "candidate", "content": "Не делал пока такую автоматизацию."},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert question.endswith("?")
    assert "если" in normalized
    assert "с нуля" in normalized or "шаг" in normalized


@pytest.mark.asyncio
async def test_get_next_question_uses_clarification_rephrase_without_llm_call():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=4,
        language="ru",
        question_type="clarification",
        message_history=[
            {"role": "assistant", "content": "Как вы диагностировали этот дефект?"},
            {"role": "candidate", "content": "не понял"},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert question.endswith("?")
    assert "переформулирую" in normalized
    assert "задач" in normalized
    assert "результат" in normalized
    assert "например" in normalized


@pytest.mark.asyncio
async def test_get_next_question_uses_configured_lead_question_for_main():
    lead_question = "Разберите релевантный кейс из резюме: контекст, ваш вклад и результат?"
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=3,
        language="ru",
        question_type="main",
        topic_phase="technical",
        lead_question=lead_question,
        competency_targets=["Test Strategy & Planning"],
        message_history=[],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    assert question == lead_question


@pytest.mark.asyncio
async def test_get_next_question_uses_configured_allowed_probe_for_followup():
    probe_question = "Какой конкретный риск вы закрыли этим подходом и чем подтвердили результат?"
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=4,
        language="ru",
        question_type="followup",
        shallow_reason="no_depth_indicators",
        allowed_probes=[probe_question],
        message_history=[
            {"role": "assistant", "content": "Опишите ваш подход к тест-стратегии."},
            {"role": "candidate", "content": "По ситуации, обычно стандартно."},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    assert question == probe_question


@pytest.mark.asyncio
async def test_get_next_question_uses_contextual_followup_for_resume_anchor():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=4,
        language="ru",
        question_type="followup",
        shallow_reason="no_depth_indicators",
        resume_anchor="Построение дэшборда для мониторинга в Grafana",
        message_history=[
            {"role": "assistant", "content": "Расскажите о вашем подходе к мониторингу."},
            {"role": "candidate", "content": "мониторинг и алерты"},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert "графана" in normalized or "grafana" in normalized
    assert "личный вклад" in normalized
    assert "измеримый результат" in normalized


@pytest.mark.asyncio
async def test_get_next_question_uses_qa_competency_specific_followup():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=5,
        language="ru",
        question_type="followup",
        shallow_reason="no_depth_indicators",
        competency_targets=["API & Performance Testing"],
        message_history=[
            {"role": "assistant", "content": "Как вы тестировали API в критичном релизе?"},
            {"role": "candidate", "content": "ну в целом стандартно"},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)
    normalized = question.lower()

    assert "endpoint" in normalized or "api" in normalized
    assert "негатив" in normalized
    assert question.endswith("?")


@pytest.mark.asyncio
async def test_get_next_question_uses_structured_reframe_for_low_signal_streak():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=5,
        language="ru",
        question_type="structured_reframe",
        verification_target="postgresql",
        message_history=[
            {"role": "assistant", "content": "Как вы тестировали запросы к PostgreSQL в production?"},
            {"role": "candidate", "content": "ну по ситуации"},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert question.endswith("?")
    assert "postgresql" in normalized
    assert "что вы сделали" in normalized
    assert "результат" in normalized


@pytest.mark.asyncio
async def test_get_next_question_uses_competency_specific_structured_reframe_for_qa():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=6,
        language="ru",
        question_type="structured_reframe",
        competency_targets=["API & Performance Testing"],
        message_history=[
            {"role": "assistant", "content": "Как вы тестировали API в критичном релизе?"},
            {"role": "candidate", "content": "сложно сказать"},
        ],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)
    normalized = question.lower()

    assert "api" in normalized
    assert "endpoint" in normalized or "сценар" in normalized
    assert question.endswith("?")


def test_recent_candidate_requested_move_on_detects_wrote_above_phrase():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=4,
        language="ru",
        message_history=[
            {"role": "assistant", "content": "Какой кейс можете привести?"},
            {"role": "candidate", "content": "уже писал выше, давайте дальше"},
        ],
    )

    assert _recent_candidate_requested_move_on(ctx) is True


@pytest.mark.asyncio
async def test_get_next_question_skips_non_matching_language_configured_lead():
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=3,
        language="en",
        question_type="main",
        topic_phase="technical",
        lead_question="Разберите технический кейс из резюме: контекст, решение и результат.",
        competency_targets=["API Design & Protocols"],
        message_history=[],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    assert "api" in question.lower() or "service" in question.lower() or "architecture" in question.lower()
    assert "разберите" not in question.lower()


@pytest.mark.asyncio
async def test_behavioral_closing_question_is_competency_aware_for_leadership():
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=8,
        language="en",
        question_type="main",
        topic_phase="behavioral_closing",
        competency_targets=["Leadership & Influence"],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert "lead" in normalized or "influence" in normalized
    assert "pressure" in normalized


@pytest.mark.asyncio
async def test_behavioral_closing_question_is_competency_aware_for_collaboration_in_russian():
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=8,
        language="ru",
        question_type="main",
        topic_phase="behavioral_closing",
        competency_targets=["Cross-team Collaboration"],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert "кросс-команд" in normalized
    assert "напряж" in normalized


@pytest.mark.asyncio
async def test_resume_followup_uses_general_question_when_anchor_is_non_experience():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=2,
        language="ru",
        question_type="main",
        topic_phase="resume_followup",
        resume_anchor="Желаемая должность и зарплата",
        competency_targets=["Debugging & Problem Decomposition"],
        message_history=[],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert "желаемая должность" not in normalized
    assert "давайте пройдем по вашему опыту" in normalized


@pytest.mark.asyncio
async def test_resume_followup_uses_general_question_when_anchor_is_low_signal_title():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=2,
        language="ru",
        question_type="main",
        topic_phase="resume_followup",
        resume_anchor="— Руководитель группы разработки",
        competency_targets=["Debugging & Problem Decomposition"],
        message_history=[],
    )

    question = await LLMInterviewer(_NoCallClient()).get_next_question(ctx)

    normalized = question.lower()
    assert "руководитель группы разработки" not in normalized
    assert "давайте пройдем по вашему опыту" in normalized


def test_normalize_question_output_strips_verbose_preamble():
    raw = (
        "Я понимаю, что масштабирование важно и требует системного подхода. "
        "Однако как backend-инженер вы должны учитывать много факторов. "
        "Расскажите, как бы вы проектировали REST API для высокой нагрузки с учетом безопасности и кэширования?"
    )
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=3,
        language="ru",
        question_type="main",
    )

    question = _normalize_question_output(raw, ctx)

    assert question.endswith("?")
    assert len(question) <= 220
    assert len(question.split()) <= 36


def test_normalize_question_output_replaces_ambiguous_short_fragment_with_fallback():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=5,
        language="ru",
        question_type="main",
        lead_question="Разберите один конкретный кейс: задача, ваши шаги и результат?",
    )

    question = _normalize_question_output("как вы их диагностировали?", ctx)

    assert question.endswith("?")
    assert "ваши шаги" in question.lower()
    assert "результат" in question.lower()


def test_build_system_prompt_includes_scored_metrics_runtime_hint():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=4,
        language="ru",
        question_type="main",
        topic_phase="technical",
        question_block="technical_depth",
        question_tier="advanced",
        lead_question="Разберите сложный кейс: как диагностировали первопричину и подтвердили фикс?",
        allowed_probes=["Какие проверки добавили после фикса?"],
        scored_metrics=["technical_depth", "problem_solving", "ownership"],
    )

    prompt = _build_system_prompt(ctx)

    assert "Структурная цель вопроса" in prompt
    assert "Текущий блок: technical_depth" in prompt
    assert "Фокус оцениваемых метрик: technical_depth, problem_solving, ownership" in prompt
    assert "Разберите сложный кейс" in prompt


def test_build_system_prompt_includes_asked_topics_and_transcript_summary():
    ctx = InterviewContext(
        target_role="qa_engineer",
        question_number=5,
        language="ru",
        question_type="main",
        asked_topics=[
            "technical|technical_foundation|core|postgresql|test strategy planning",
            "technical|technical_depth|advanced|api|api performance testing",
        ],
        transcript_summary=[
            "technical_foundation: описал risk-based приоритизацию и smoke/regression набор",
            "technical_depth: объяснил API проверки и ретест после hotfix",
        ],
    )

    prompt = _build_system_prompt(ctx)

    assert "Уже покрытые сигнатуры тем" in prompt
    assert "Краткий summary диалога" in prompt
