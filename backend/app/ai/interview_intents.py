from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9_+#.-]+")
_REQUEST_STYLE_RE = re.compile(
    r"\b(дай|дайте|приведи|приведите|покажи|покажите|можешь|можете|can you|please|show|give)\b"
)
_CHALLENGE_STYLE_RE = re.compile(
    r"\b(ты|you)\b.*\b(сам|yourself|можешь|can)\b|\bсам\s+ответ(ь|ить)\b"
)

_CLARIFY_MARKERS = (
    "не понял",
    "непонят",
    "уточни",
    "уточните",
    "поясни",
    "поясните",
    "что именно",
    "в чем вопрос",
    "в чём вопрос",
    "what do you mean",
    "not clear",
    "clarify",
)
_EXAMPLE_REQUEST_MARKERS = (
    "какой кейс",
    "пример",
    "на примере",
    "дай кейс",
    "приведи кейс",
    "show example",
    "give example",
    "which case",
)
_META_MARKERS = (
    "как проходит",
    "формат интервью",
    "сколько вопросов",
    "по времени",
    "что дальше",
    "what's next",
    "how many questions",
    "interview format",
)
_CHALLENGE_MARKERS = (
    "а ты сам",
    "ты сам",
    "сам ответь",
    "сам ответить можешь",
    "зачем ты спрашиваешь",
    "can you answer yourself",
    "why are you asking",
)
_RESUME_FOCUS_MARKERS = (
    "по моему опыту",
    "по моей работе",
    "по резюме",
    "в моем опыте",
    "в моём опыте",
    "по моему контексту",
    "based on my experience",
    "from my resume",
)
_DONT_KNOW_MARKERS = (
    "не знаю",
    "незнаю",
    "не помню",
    "затрудняюсь",
    "без понятия",
    "don't know",
    "not sure",
)
_GENERAL_WEAK_MARKERS = (
    "везде",
    "логи",
    "api",
    "апи",
    "проверю",
    "посмотрю",
    "статусы",
    "как обычно",
    "по ситуации",
    "everywhere",
    "logs",
    "i'll check",
)
_OFFTOPIC_MARKERS = (
    "погода",
    "анекдот",
    "шутка",
    "музыка",
    "спорт",
    "weather",
    "joke",
    "music",
)


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text.lower())]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _looks_like_question(text: str) -> bool:
    return "?" in text or text.startswith(("как ", "что ", "почему ", "where ", "what ", "how "))


def _is_request_for_example(text: str) -> bool:
    """Detect *request* for example/case, not regular answer containing 'например'."""
    if not text:
        return False
    has_example_word = _contains_any(text, _EXAMPLE_REQUEST_MARKERS)
    if not has_example_word:
        return False
    if "?" in text:
        return True
    if _REQUEST_STYLE_RE.search(text):
        return True
    # Short utterances like "пример", "кейс", "на примере"
    if len(text.split()) <= 4:
        return True
    return False


def _is_weak_answer(message: str, context: dict[str, Any]) -> bool:
    msg = _norm(message)
    if not msg:
        return False
    words = msg.split()
    if _contains_any(msg, _GENERAL_WEAK_MARKERS):
        return True
    if len(words) <= 2:
        return True
    current_question = _norm(str(context.get("current_question") or ""))
    if not current_question:
        return False
    q_tokens = set(_tokens(current_question))
    a_tokens = set(_tokens(msg))
    overlap = len(q_tokens & a_tokens)
    # Short topical but shallow answer.
    if len(words) <= 5 and overlap >= 1:
        return True
    return False


def classify_candidate_intent(message: str, context: dict) -> dict:
    msg = _norm(message)
    if not msg:
        return {
            "intent": "offtopic",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "clarify",
            "reason": "empty_or_blank_message",
        }

    if _contains_any(msg, _CHALLENGE_MARKERS) or _CHALLENGE_STYLE_RE.search(msg):
        return {
            "intent": "challenge_interviewer",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "answer_meta_then_redirect",
            "reason": "candidate_challenges_interviewer",
        }

    if _contains_any(msg, _RESUME_FOCUS_MARKERS):
        return {
            "intent": "request_resume_focus",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "resume_redirect",
            "reason": "candidate_requests_resume_context",
        }

    if _contains_any(msg, _CLARIFY_MARKERS) or msg in {"что?", "что", "what?"}:
        return {
            "intent": "clarification_request",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "clarify",
            "reason": "candidate_requests_clarification",
        }

    if _is_request_for_example(msg):
        return {
            "intent": "request_example",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "give_example_scenario",
            "reason": "candidate_requests_example_or_case",
        }

    if _contains_any(msg, _META_MARKERS):
        return {
            "intent": "meta_question",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "answer_meta_then_redirect",
            "reason": "candidate_asks_about_process",
        }

    if _contains_any(msg, _DONT_KNOW_MARKERS):
        return {
            "intent": "dont_know",
            "should_count_as_answer": True,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "pressure_followup",
            "reason": "candidate_explicitly_does_not_know",
        }

    if _contains_any(msg, _OFFTOPIC_MARKERS):
        return {
            "intent": "offtopic",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "switch_topic",
            "reason": "candidate_message_offtopic",
        }

    if _looks_like_question(msg):
        return {
            "intent": "meta_question",
            "should_count_as_answer": False,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "answer_meta_then_redirect",
            "reason": "candidate_asked_question_instead_of_answer",
        }

    if _is_weak_answer(msg, context or {}):
        return {
            "intent": "weak_answer",
            "should_count_as_answer": True,
            "should_advance_phase": False,
            "should_advance_scenario": False,
            "recommended_policy": "pressure_followup",
            "reason": "answer_is_too_generic_or_too_short",
        }

    return {
        "intent": "answer",
        "should_count_as_answer": True,
        "should_advance_phase": True,
        "should_advance_scenario": True,
        "recommended_policy": "continue",
        "reason": "candidate_provided_substantive_answer",
    }
