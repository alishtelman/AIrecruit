"""
transition_phrases.py
─────────────────────
Phrase banks for humanising the interview flow.

Three main entry points:
  • build_topic_transition(language, answer_class, saturation_reason, is_last_question)
      → prepend-phrase when advancing to next main topic
  • build_soft_reframe(language, role)
      → gentler pressure phrase (replaces the blunt "давайте конкретнее")
  • build_closing_marker(language)
      → prefix for the very last interview question
"""

from __future__ import annotations

import random

# ──────────────────────────────────────────────────────────────────────────────
# Internal phrase banks
# ──────────────────────────────────────────────────────────────────────────────

_TRANSITION_NEUTRAL_RU = [
    "Хорошо, спасибо. Двигаемся дальше.",
    "Понял, записал. Перейдём к следующей теме.",
    "Ок, записал. Идём дальше.",
    "Принял. Следующий вопрос.",
    "Спасибо. Переходим к следующей теме.",
    "Записал. Переходим дальше.",
]

_TRANSITION_NEUTRAL_EN = [
    "Got it, thanks. Moving on.",
    "Noted. Let's go to the next topic.",
    "Understood. Next question.",
    "Okay, recorded. Moving to the next area.",
    "Thanks. Let's continue.",
    "Noted. Let's move on.",
]

_TRANSITION_AFFIRM_RU = [
    "Хороший пример, спасибо. Двигаемся дальше.",
    "Отлично, это полезный кейс. Переходим к следующей теме.",
    "Понял, чёткий ответ. Идём дальше.",
    "Спасибо за конкретику. Следующий вопрос.",
    "Ценный опыт, записал. Переходим.",
]

_TRANSITION_AFFIRM_EN = [
    "Great example, thanks. Let's move on.",
    "Good answer, I have what I need. Next topic.",
    "Solid, noted. Moving to the next area.",
    "Thanks for the detail. Let's continue.",
    "Useful context, recorded. Moving on.",
]

_TRANSITION_WEAK_RU = [
    "Понял. Перейдём к следующей теме.",
    "Записал. Идём дальше.",
    "Ок, спасибо. Следующий вопрос.",
    "Принял ответ. Переходим.",
]

_TRANSITION_WEAK_EN = [
    "Understood. Let's move to the next topic.",
    "Noted. Next question.",
    "Okay, thanks. Moving on.",
    "Got it. Let's continue.",
]

_CLOSING_MARKER_RU = [
    "И последний вопрос нашего интервью.",
    "Завершающий вопрос.",
    "Последний вопрос —",
    "И финальный вопрос.",
]

_CLOSING_MARKER_EN = [
    "And the final question of our interview.",
    "Last question.",
    "One final question —",
    "And to wrap up —",
]

_SOFT_REFRAME_RU = [
    "Понял общий подход — если есть конкретный пример из практики, давайте на нём.",
    "Хорошо. Можете привести конкретный кейс из своей работы?",
    "Понял. Попробуйте вспомнить похожую ситуацию из реального проекта.",
    "Записал. Если есть конкретный случай — расскажите о нём.",
    "Ок. Есть ли в вашей практике похожий пример, который можно разобрать?",
]

_SOFT_REFRAME_EN = [
    "Understood the general approach — if you have a concrete example from your work, let's use that.",
    "Got it. Can you walk me through a specific case from your experience?",
    "Okay. Try to think of a similar situation from a real project.",
    "Noted. If you have a concrete instance, tell me about it.",
    "Sure. Is there a practical example from your work we can dig into?",
]

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def build_topic_transition(
    language: str,
    answer_class: str = "",
    saturation_reason: str | None = None,
    is_last_question: bool = False,
) -> str:
    """Return a short transition phrase to prepend before a new main-topic question.

    Returns an empty string when no transition is warranted (e.g. for follow-ups).
    """
    is_en = str(language).lower().startswith("en")

    if is_last_question:
        pool = _CLOSING_MARKER_EN if is_en else _CLOSING_MARKER_RU
        return random.choice(pool)

    answer_class = str(answer_class or "").strip().lower()
    saturation_reason = str(saturation_reason or "").strip().lower()

    is_strong = (
        answer_class == "strong"
        or saturation_reason in {"topic_mastered", "topic_saturated"}
    )
    is_weak = answer_class in {"generic", "evasive", "no_experience_honest", "weak"}

    if is_strong:
        pool = _TRANSITION_AFFIRM_EN if is_en else _TRANSITION_AFFIRM_RU
    elif is_weak:
        pool = _TRANSITION_WEAK_EN if is_en else _TRANSITION_WEAK_RU
    else:
        pool = _TRANSITION_NEUTRAL_EN if is_en else _TRANSITION_NEUTRAL_RU

    return random.choice(pool)


_DEEP_TECHNICAL_PRAISE_RU = [
    "Отличный пример, спасибо за детали.",
    "Это показывает системное мышление. Давайте углубимся:",
    "Хороший подход. Позвольте задать уточняющий вопрос:",
    "Интересный кейс. Если копнуть чуть глубже:",
]

_DEEP_TECHNICAL_PRAISE_EN = [
    "Great example, thanks for the details.",
    "That shows systematic thinking. Let's dig deeper:",
    "Good approach. Let me ask a follow-up:",
    "Interesting case. If we go a bit deeper:",
]


def build_soft_reframe(language: str, role: str = "") -> str:
    """Return a gentle pressure phrase (human-sounding alternative to blunt 'конкретнее')."""
    is_en = str(language).lower().startswith("en")
    pool = _SOFT_REFRAME_EN if is_en else _SOFT_REFRAME_RU
    return random.choice(pool)


def build_deep_technical_praise(language: str) -> str:
    """Return a praise phrase before asking a deep technical follow-up to a strong answer."""
    is_en = str(language).lower().startswith("en")
    pool = _DEEP_TECHNICAL_PRAISE_EN if is_en else _DEEP_TECHNICAL_PRAISE_RU
    return random.choice(pool)


def prepend_transition(transition: str, question: str) -> str:
    """Combine transition phrase + question into a single natural message."""
    t = transition.strip()
    q = question.strip()
    if not t:
        return q
    if not q:
        return t
    # If transition ends with '—' or '-', join without period
    if t.endswith("—") or t.endswith("-"):
        return f"{t} {q}"
    # If transition already ends with punctuation, just newline-join
    if t[-1] in ".!?":
        return f"{t}\n\n{q}"
    return f"{t}.\n\n{q}"
