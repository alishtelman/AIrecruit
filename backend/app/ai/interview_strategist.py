"""
Interview strategist (v2).

Python keeps state/guardrails while LLM decides the next interviewer action.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai.model_preferences import resolve_llm_runtime_model
from app.ai.providers import LLMProvider, get_llm_provider
from app.ai.runtime_status import record_ai_error, record_ai_success
from app.core.config import settings

logger = logging.getLogger(__name__)

ActionType = Literal[
    "ask_resume_followup",
    "pressure_followup",
    "clarify",
    "answer_meta_then_redirect",
    "start_scenario",
    "continue_scenario",
    "switch_topic",
    "close_interview",
]

PhaseType = Literal[
    "intro",
    "resume_deep_dive",
    "technical_case",
    "behavioral",
    "closing",
]

_ALLOWED_ACTIONS: set[str] = {
    "ask_resume_followup",
    "pressure_followup",
    "clarify",
    "answer_meta_then_redirect",
    "start_scenario",
    "continue_scenario",
    "switch_topic",
    "close_interview",
}

_ACTION_ALIASES: dict[str, str] = {
    "ask_new_topic": "switch_topic",
    "follow_up": "pressure_followup",
    "simplify": "clarify",
}

_ALLOWED_PHASES: set[str] = {
    "intro",
    "resume_deep_dive",
    "technical_case",
    "behavioral",
    "closing",
}

_JSON_SCHEMA_NOTE = (
    '{\n'
    '  "action": "ask_resume_followup|pressure_followup|clarify|answer_meta_then_redirect|start_scenario|continue_scenario|switch_topic|close_interview",\n'
    '  "question_text": "string",\n'
    '  "target_competency": "string",\n'
    '  "phase": "intro|resume_deep_dive|technical_case|behavioral|closing",\n'
    '  "scenario_id": "string|null",\n'
    '  "scenario_step": "number|null",\n'
    '  "difficulty_tier": 1,\n'
    '  "reason": "string",\n'
    '  "expected_signal": "string"\n'
    '}'
)

_REASONING_SCHEMA_NOTE = (
    '{\n'
    '  "candidate_understanding": "string",\n'
    '  "candidate_cooperation_level": "string",\n'
    '  "conversation_problem": "string",\n'
    '  "missing_signal": "string",\n'
    '  "resume_evidence_status": "string",\n'
    '  "best_next_move": "ask_resume_followup|pressure_followup|clarify|answer_meta_then_redirect|start_scenario|continue_scenario|switch_topic|close_interview",\n'
    '  "conversational_intent": "string",\n'
    '  "information_target": "string",\n'
    '  "question_goal": "string",\n'
    '  "question_style": "conversational|probing|simplified|edge_case",\n'
    '  "why_this_move": "string"\n'
    '}'
)

_QUESTION_PHRASING_SCHEMA_NOTE = '{ "question_text": "string" }'

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9+#.-]+")
_STOP_TOKENS = {
    "как",
    "что",
    "какой",
    "какие",
    "где",
    "почему",
    "когда",
    "вы",
    "ты",
    "это",
    "этот",
    "эта",
    "и",
    "или",
    "но",
    "для",
    "про",
    "the",
    "a",
    "an",
    "how",
    "what",
    "which",
    "where",
    "when",
    "why",
    "you",
    "your",
    "with",
    "for",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "about",
}

_ROLE_FALLBACK_QUESTIONS: dict[str, str] = {
    "qa_engineer": (
        "Представьте: пользователь сделал перевод, деньги списались, но статус операции — ошибка. "
        "Что вы проверите первым и почему?"
    ),
    "backend_engineer": (
        "Представьте: API внезапно выросло до 3x нагрузки. Что вы проверите первым и какой безопасный шаг сделаете за 15 минут?"
    ),
    "frontend_engineer": (
        "Представьте: после релиза страница стала тормозить только на мобильных. Как вы локализуете проблему и что померяете первым?"
    ),
    "devops_engineer": (
        "Представьте: после деплоя выросли 5xx и latency. Какой ваш первый triage-план по шагам?"
    ),
    "data_scientist": (
        "Представьте: метрика модели упала после релиза. Как проверите, это data drift, bug в пайплайне или смена поведения пользователей?"
    ),
    "product_manager": (
        "Представьте: фича не дала ожидаемого роста. Какие 3 проверки вы сделаете, чтобы понять причину и следующий шаг?"
    ),
    "mobile_engineer": (
        "Представьте: после обновления вырос crash rate только на Android 13. Как вы воспроизведете, локализуете и безопасно откатите риск?"
    ),
    "designer": (
        "Представьте: после редизайна упала конверсия в ключевом сценарии. Какие данные и пользовательские шаги вы проверите первыми?"
    ),
}


@dataclass
class InterviewStrategistContext:
    role: str
    language: str = "ru"
    resume_summary: str = ""
    role_competency_map: Any = field(default_factory=dict)
    interview_state_v2: dict[str, Any] = field(default_factory=dict)
    last_question: str = ""
    last_answer: str = ""
    last_answer_evaluation: dict[str, Any] | None = None
    transcript_summary: list[str] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)
    available_scenarios: list[dict[str, Any]] = field(default_factory=list)
    conversational_interviewer_mode: bool = False
    policy_action: str = ""
    candidate_intent: str = ""
    missing_signal: str = ""
    pressure_goal: str = ""
    reasoning_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuestionDecision:
    action: ActionType
    question_text: str
    target_competency: str
    phase: PhaseType
    scenario_id: str | None
    scenario_step: int
    difficulty_tier: int
    reason: str
    expected_signal: str
    strategist_raw_response: str = ""
    strategist_json_valid: bool = False
    strategist_repair_applied: bool = False
    strategist_retry_used: bool = False
    strategist_error_reason: str = ""
    conversational_intent: str = ""
    information_target: str = ""
    ai_provider: str = ""
    requested_model: str = ""
    actual_model_used: str = ""
    provider_attempts: list[dict[str, Any]] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    openrouter_fallback_used: bool = False


def _question_signature(question: str) -> str:
    tokens = [
        token.lower()
        for token in _TOKEN_RE.findall(question.lower())
        if token.lower() not in _STOP_TOKENS and len(token) > 2
    ]
    return " ".join(sorted(set(tokens)))


def _is_repeated_question(question: str, asked_questions: list[str]) -> bool:
    normalized = _WS_RE.sub(" ", question.strip().lower())
    if not normalized:
        return True
    if any(_WS_RE.sub(" ", str(item or "").strip().lower()) == normalized for item in asked_questions):
        return True
    signature = _question_signature(normalized)
    if not signature:
        return False
    signature_tokens = set(signature.split())
    for asked in asked_questions[-20:]:
        other_signature = _question_signature(str(asked or ""))
        if not other_signature:
            continue
        other_tokens = set(other_signature.split())
        if not other_tokens:
            continue
        overlap = len(signature_tokens & other_tokens) / float(max(1, len(signature_tokens)))
        if overlap >= 0.75:
            return True
    return False


def _sanitize_question_text(value: str) -> str:
    text = _WS_RE.sub(" ", str(value or "").strip())
    if not text:
        return ""
    if "?" in text:
        parts = text.split("?")
        first = parts[0].strip()
        text = f"{first}?" if first else text
    if not text.endswith("?"):
        text = f"{text}?"
    return text


def _extract_competencies(role_competency_map: Any) -> list[str]:
    if isinstance(role_competency_map, list):
        values = [str(item).strip() for item in role_competency_map if str(item).strip()]
        return values
    if isinstance(role_competency_map, dict):
        if isinstance(role_competency_map.get("competencies"), list):
            values = [str(item).strip() for item in role_competency_map.get("competencies", []) if str(item).strip()]
            if values:
                return values
        if isinstance(role_competency_map.get("core_competency_order"), list):
            values = [
                str(item).strip()
                for item in role_competency_map.get("core_competency_order", [])
                if str(item).strip()
            ]
            if values:
                return values
    return []


def _pick_fallback_target_competency(ctx: InterviewStrategistContext) -> str:
    state = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
    current = str(state.get("current_competency") or "").strip()
    if current:
        return current
    competencies = _extract_competencies(ctx.role_competency_map)
    if competencies:
        return competencies[0]
    return "Technical depth"


def _pick_fallback_question(ctx: InterviewStrategistContext) -> tuple[str, str | None, int]:
    scenarios = ctx.available_scenarios if isinstance(ctx.available_scenarios, list) else []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("scenario_id") or scenario.get("case_id") or "").strip() or None
        questions = scenario.get("questions")
        if not isinstance(questions, list):
            continue
        for idx, question in enumerate(questions):
            candidate = _sanitize_question_text(str(question or ""))
            if not candidate:
                continue
            if not _is_repeated_question(candidate, ctx.asked_questions):
                return candidate, scenario_id, idx
    role = str(ctx.role or "").strip()
    generic = _ROLE_FALLBACK_QUESTIONS.get(role, _ROLE_FALLBACK_QUESTIONS["qa_engineer"])
    return _sanitize_question_text(generic), None, 0


def _normalize_action(value: str, *, default_action: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _ACTION_ALIASES.get(normalized, normalized)
    if normalized in _ALLOWED_ACTIONS:
        return normalized
    return default_action if default_action in _ALLOWED_ACTIONS else "clarify"


def _infer_phase_from_action(action: str, state: dict[str, Any]) -> str:
    current_phase = str(state.get("phase") or "resume_deep_dive").strip().lower()
    if current_phase not in _ALLOWED_PHASES:
        current_phase = "resume_deep_dive"
    if action == "close_interview":
        return "closing"
    if action in {"ask_resume_followup"}:
        return "resume_deep_dive"
    if action in {"start_scenario", "continue_scenario", "pressure_followup"} and current_phase in {"intro", "resume_deep_dive"}:
        return "technical_case"
    if action == "switch_topic" and current_phase == "behavioral":
        return "behavioral"
    if action in {"clarify", "answer_meta_then_redirect"}:
        return current_phase
    return current_phase


def _pick_diversified_fallback_question(
    *,
    ctx: InterviewStrategistContext,
    action: str,
    asked_questions: list[str],
) -> tuple[str, str | None, int]:
    _ = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
    _ = _pick_fallback_target_competency(ctx)
    scenario_question, scenario_id, scenario_step = _pick_fallback_question(ctx)
    candidates: list[tuple[str, str | None, int]] = []

    if action == "ask_resume_followup":
        q = (
            f"В вашем опыте по роли {ctx.role}: какую задачу вы решали лично, какие 2 шага сделали и какой был результат?"
            if (ctx.language or "").lower().startswith("ru")
            else f"In your {ctx.role} experience: which task did you personally solve, what 2 steps did you take, and what was the result?"
        )
        candidates.append((_sanitize_question_text(q), None, 0))
    elif action == "pressure_followup":
        q = (
            "Окей, давайте конкретнее: назовите первые 2 шага, какие данные проверяете и какой сигнал подтвердит гипотезу?"
            if (ctx.language or "").lower().startswith("ru")
            else "Okay, let's make it concrete: name the first 2 steps, what data you check, and which signal confirms the hypothesis?"
        )
        candidates.append((_sanitize_question_text(q), None, 0))
    elif action in {"clarify", "answer_meta_then_redirect"}:
        q = (
            f"Окей, поясню на конкретном примере. {scenario_question}"
            if (ctx.language or "").lower().startswith("ru")
            else f"Okay, let me simplify with a concrete example. {scenario_question}"
        )
        candidates.append((_sanitize_question_text(q), scenario_id, scenario_step))

    candidates.append((scenario_question, scenario_id, scenario_step))
    candidates.append((_sanitize_question_text(_ROLE_FALLBACK_QUESTIONS.get(ctx.role, _ROLE_FALLBACK_QUESTIONS["qa_engineer"])), None, 0))

    for question, sid, step in candidates:
        if not question:
            continue
        if not _is_repeated_question(question, asked_questions):
            return question, sid, step
    return scenario_question, scenario_id, scenario_step


def _fallback_decision(ctx: InterviewStrategistContext, *, reason: str) -> QuestionDecision:
    state = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
    fallback_counter = max(0, int(state.get("fallback_counter") or 0))
    fallback_modes = [
        "ask_resume_followup",
        "pressure_followup",
        "start_scenario",
        "clarify",
    ]
    default_action = fallback_modes[fallback_counter % len(fallback_modes)]
    question_text, scenario_id, scenario_step = _pick_diversified_fallback_question(
        ctx=ctx,
        action=default_action,
        asked_questions=ctx.asked_questions,
    )
    target_competency = _pick_fallback_target_competency(ctx)
    action: ActionType
    if default_action in _ALLOWED_ACTIONS:
        action = default_action  # type: ignore[assignment]
    else:
        action = "clarify"
    if scenario_id and scenario_step > 0 and action == "start_scenario":
        action = "continue_scenario"
    if scenario_id and scenario_step == 0 and action == "continue_scenario":
        action = "start_scenario"
    return QuestionDecision(
        action=action,
        question_text=question_text,
        target_competency=target_competency,
        phase=_infer_phase_from_action(action, state),
        scenario_id=scenario_id,
        scenario_step=max(0, int(scenario_step)),
        difficulty_tier=max(1, min(5, int((ctx.interview_state_v2 or {}).get("difficulty_tier") or 3))),
        reason=reason,
        expected_signal="concrete_work_example",
        strategist_raw_response="",
        strategist_json_valid=False,
        strategist_repair_applied=False,
        strategist_retry_used=False,
        strategist_error_reason=reason,
        conversational_intent=_default_conversational_intent_from_action(action),
        information_target=target_competency,
    )


def _build_reasoning_system_prompt(language: str) -> str:
    if (language or "").lower().startswith("en"):
        return (
            "You are a senior technical interviewer.\n"
            "First reason, then ask. Return only reasoning JSON, never question text.\n"
            "Interview style: calm, professional, human, conversational, probing but respectful.\n"
            "Avoid robotic wording and repeated templates.\n"
            "Do not ask abstract prompts like 'analyze a case' or 'describe your approach'.\n"
            "If candidate is confused, naturally simplify with concrete context.\n"
            "If candidate is strong, go deeper or harder.\n"
            "If candidate is evasive, politely redirect to one concrete signal.\n"
            "If candidate asks meta question, answer briefly then continue interview naturally.\n"
            "Resume is personalization only; role competency map is the primary focus.\n"
            "Use policy_action and reasoning_hints from context as hard guidance for next move.\n"
            "If policy_action is clarify/pressure_followup/ask_resume_followup, align best_next_move accordingly.\n"
            "Keep interview pacing: intro -> warmup -> experience deep-dive -> technical probing -> harder edge cases -> behavioral -> closing.\n"
            "Return ONLY valid JSON. No markdown. No extra text.\n"
            "Use exactly this schema:\n"
            f"{_REASONING_SCHEMA_NOTE}"
        )
    return (
        "Ты senior технический интервьюер.\n"
        "Сначала рассуждай, потом задавай вопрос. Сейчас верни только reasoning JSON, без question_text.\n"
        "Стиль интервью: спокойный, профессиональный, живой, разговорный, уважительно-проникающий в детали.\n"
        "Избегай роботизированных формулировок и повторяющихся шаблонов.\n"
        "Запрещено абстрактное «разберите кейс» и «опишите подход» без контекста.\n"
        "Если кандидат запутался — упрощай естественно и давай конкретный контекст.\n"
        "Если кандидат сильный — усложняй и углубляй.\n"
        "Если кандидат уклоняется — вежливо возвращай к одному конкретному сигналу.\n"
        "Если кандидат задаёт meta-вопрос — коротко ответь и естественно продолжай интервью.\n"
        "Резюме используется для персонализации, но фокус интервью задаёт role competency map.\n"
        "Используй policy_action и reasoning_hints из context как жёсткие подсказки для следующего хода.\n"
        "Если policy_action = clarify/pressure_followup/ask_resume_followup, согласуй best_next_move с ним.\n"
        "Держи pacing интервью: intro -> warm-up -> experience deep-dive -> technical probing -> harder edge cases -> behavioral -> closing.\n"
        "Верни ТОЛЬКО валидный JSON. Без markdown и без текста до/после.\n"
        "Используй строго эту схему:\n"
        f"{_REASONING_SCHEMA_NOTE}"
    )


def _build_question_phrasing_system_prompt(language: str) -> str:
    if (language or "").lower().startswith("en"):
        return (
            "You are a technical interviewer phrase generator.\n"
            "Turn reasoning into one natural interviewer utterance.\n"
            "Style: calm, professional, human, conversational.\n"
            "Do not sound robotic.\n"
            "Avoid templates like 'analyze a case' or 'describe your approach'.\n"
            "Prefer: 'Let's use an example', 'Imagine this situation', 'Okay, and if...'.\n"
            "Output ONLY JSON using this schema:\n"
            f"{_QUESTION_PHRASING_SCHEMA_NOTE}"
        )
    return (
        "Ты формулировщик вопросов интервью.\n"
        "Преобразуй reasoning в один естественный вопрос интервьюера.\n"
        "Стиль: спокойный, профессиональный, живой, разговорный.\n"
        "Не пиши роботизированно.\n"
        "Запрещено: «разберите кейс», «опишите подход».\n"
        "Предпочтительно: «Давайте на примере», «Представьте ситуацию», «Окей, а если...».\n"
        "Верни ТОЛЬКО JSON по схеме:\n"
        f"{_QUESTION_PHRASING_SCHEMA_NOTE}"
    )


def _context_payload(ctx: InterviewStrategistContext) -> dict[str, Any]:
    return {
        "role": ctx.role,
        "language": ctx.language,
        "resume_summary": ctx.resume_summary,
        "role_competency_map": ctx.role_competency_map,
        "interview_state_v2": ctx.interview_state_v2,
        "last_question": ctx.last_question,
        "last_answer": ctx.last_answer,
        "last_answer_evaluation": ctx.last_answer_evaluation,
        "transcript_summary": ctx.transcript_summary[-10:],
        "asked_questions": ctx.asked_questions[-30:],
        "available_scenarios": ctx.available_scenarios,
        "conversational_interviewer_mode": bool(ctx.conversational_interviewer_mode),
        "policy_action": str(ctx.policy_action or ""),
        "candidate_intent": str(ctx.candidate_intent or ""),
        "missing_signal": str(ctx.missing_signal or ""),
        "pressure_goal": str(ctx.pressure_goal or ""),
        "reasoning_hints": ctx.reasoning_hints if isinstance(ctx.reasoning_hints, dict) else {},
    }


def _infer_interview_pacing_stage(ctx: InterviewStrategistContext) -> str:
    state = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
    phase = str(state.get("phase") or "").strip().lower()
    turns = max(
        len(ctx.asked_questions),
        int(state.get("total_turns") or 0),
    )
    if phase == "intro":
        return "intro"
    if phase == "resume_deep_dive":
        return "warm_up" if turns <= 3 else "experience_deep_dive"
    if phase == "technical_case":
        return "harder_edge_cases" if turns >= 8 else "technical_probing"
    if phase == "behavioral":
        return "behavioral"
    if phase == "closing":
        return "closing"
    return "technical_probing"


def _build_reasoning_context_payload(ctx: InterviewStrategistContext) -> dict[str, Any]:
    payload = _context_payload(ctx)
    payload["interview_pacing_stage"] = _infer_interview_pacing_stage(ctx)
    return payload


def _map_reasoning_move_to_action(
    move: str,
    *,
    policy_context: dict[str, Any],
) -> str:
    normalized_move = _normalize_action(
        str(move or "").strip().lower(),
        default_action=_fallback_action_from_policy(policy_context),
    )
    policy_action = _normalize_action(
        str(policy_context.get("policy_action") or "").strip().lower(),
        default_action="clarify",
    )
    # Keep policy hard intents stronger than strategist guess.
    if policy_action in {"clarify", "answer_meta_then_redirect", "ask_resume_followup", "pressure_followup"}:
        return policy_action
    return normalized_move


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(needle in normalized for needle in needles)


def _is_confusion_message(candidate_message: str) -> bool:
    return _contains_any(
        candidate_message,
        (
            "что?",
            "не понял",
            "непонятно",
            "какой кейс",
            "про что",
            "в чем вопрос",
        ),
    )


def _is_meta_question_message(candidate_message: str) -> bool:
    return _contains_any(
        candidate_message,
        (
            "а ты сам ответить можешь",
            "ты сам ответить можешь",
            "ты сам ответь",
            "зачем ты спрашиваешь",
            "can you answer yourself",
            "why are you asking",
        ),
    )


def _is_resume_personalization_request_message(candidate_message: str) -> bool:
    return _contains_any(
        candidate_message,
        (
            "давай по моему опыту",
            "по моему опыту",
            "по моей работе",
            "еще вопросы будут",
            "в моем опыте",
            "based on my experience",
            "use my experience",
        ),
    )


def _is_aggressive_or_sarcastic_message(candidate_message: str) -> bool:
    return _contains_any(
        candidate_message,
        (
            "ты зациклился",
            "фигня",
            "бред",
            "что за бред",
            "какую-то ерунду",
            "тупой вопрос",
        ),
    )


def _is_counter_question(candidate_message: str) -> bool:
    normalized = str(candidate_message or "").strip().lower()
    if not normalized:
        return False
    if "?" not in normalized:
        return False
    if _is_confusion_message(normalized):
        return False
    if _is_meta_question_message(normalized):
        return False
    if _is_resume_personalization_request_message(normalized):
        return False
    return _contains_any(
        normalized,
        (
            "какая задача",
            "что именно",
            "где именно",
            "поясни",
            "уточни",
            "в смысле",
        ),
    )


def _pick_concrete_example_question(ctx: InterviewStrategistContext) -> tuple[str, str | None, int]:
    question, scenario_id, scenario_step = _pick_fallback_question(ctx)
    return _sanitize_question_text(question), scenario_id, max(0, int(scenario_step))


def _conversation_guardrail_decision(ctx: InterviewStrategistContext) -> QuestionDecision | None:
    candidate_message = str(ctx.last_answer or "").strip()
    if not candidate_message:
        return None

    question_text, scenario_id, scenario_step = _pick_concrete_example_question(ctx)
    target_competency = _pick_fallback_target_competency(ctx)
    base_difficulty = max(1, min(5, int((ctx.interview_state_v2 or {}).get("difficulty_tier") or 3)))

    if _is_confusion_message(candidate_message):
        lang_ru = not (ctx.language or "").lower().startswith("en")
        prefix = (
            "Окей, объясню проще на конкретном примере. "
            if lang_ru
            else "Okay, let me simplify with a concrete example. "
        )
        return QuestionDecision(
            action="clarify",
            question_text=_sanitize_question_text(f"{prefix}{question_text}"),
            target_competency=target_competency,
            phase=_infer_phase_from_action("clarify", ctx.interview_state_v2 or {}),
            scenario_id=scenario_id,
            scenario_step=scenario_step,
            difficulty_tier=max(1, base_difficulty - 1),
            reason="candidate_confusion_detected",
            expected_signal="understanding_of_concrete_scenario",
        )

    if _is_meta_question_message(candidate_message):
        lang_ru = not (ctx.language or "").lower().startswith("en")
        prefix = (
            "Могу, но сейчас важно понять ваш ход мысли как кандидата. Давайте проще: "
            if lang_ru
            else "I can, but now I need to understand your reasoning as a candidate. Let's simplify: "
        )
        return QuestionDecision(
            action="answer_meta_then_redirect",
            question_text=_sanitize_question_text(f"{prefix}{question_text}"),
            target_competency=target_competency,
            phase=_infer_phase_from_action("answer_meta_then_redirect", ctx.interview_state_v2 or {}),
            scenario_id=scenario_id,
            scenario_step=scenario_step,
            difficulty_tier=max(1, base_difficulty - 1),
            reason="candidate_meta_question_detected",
            expected_signal="candidate_reasoning_on_concrete_case",
        )

    if _is_resume_personalization_request_message(candidate_message):
        lang_ru = not (ctx.language or "").lower().startswith("en")
        prefix = (
            "Ок, привяжем к вашему опыту сопровождения мобильного банка. "
            if lang_ru
            else "Okay, let's tie this to your mobile banking support experience. "
        )
        return QuestionDecision(
            action="ask_resume_followup",
            question_text=_sanitize_question_text(f"{prefix}{question_text}"),
            target_competency=target_competency,
            phase=_infer_phase_from_action("ask_resume_followup", ctx.interview_state_v2 or {}),
            scenario_id=scenario_id,
            scenario_step=scenario_step,
            difficulty_tier=base_difficulty,
            reason="candidate_requested_resume_personalization",
            expected_signal="role_competency_answer_in_personal_context",
        )

    if _is_aggressive_or_sarcastic_message(candidate_message):
        lang_ru = not (ctx.language or "").lower().startswith("en")
        prefix = (
            "Давай проще объясню, ок? "
            if lang_ru
            else "Let me explain it simpler, okay? "
        )
        return QuestionDecision(
            action="clarify",
            question_text=_sanitize_question_text(f"{prefix}{question_text}"),
            target_competency=target_competency,
            phase=_infer_phase_from_action("clarify", ctx.interview_state_v2 or {}),
            scenario_id=scenario_id,
            scenario_step=scenario_step,
            difficulty_tier=max(1, base_difficulty - 1),
            reason="candidate_aggression_or_sarcasm_detected",
            expected_signal="restored_dialogue_with_concrete_case",
        )

    if _is_counter_question(candidate_message):
        lang_ru = not (ctx.language or "").lower().startswith("en")
        bridge = (
            "Коротко: хочу понять ваш реальный рабочий подход. "
            if lang_ru
            else "Short answer: I want to understand your real working approach. "
        )
        return QuestionDecision(
            action="answer_meta_then_redirect",
            question_text=_sanitize_question_text(f"{bridge}{question_text}"),
            target_competency=target_competency,
            phase=_infer_phase_from_action("answer_meta_then_redirect", ctx.interview_state_v2 or {}),
            scenario_id=scenario_id,
            scenario_step=scenario_step,
            difficulty_tier=base_difficulty,
            reason="candidate_counter_question_detected",
            expected_signal="direct_case_answer_after_brief_clarification",
        )

    return None


def _extract_json_candidate(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    if "```" in text:
        text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _repair_payload(
    payload: dict[str, Any],
    *,
    ctx: InterviewStrategistContext,
    policy_context: dict[str, Any],
) -> dict[str, Any]:
    state = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
    policy_action = str(policy_context.get("policy_action") or "").strip().lower()
    default_action = "clarify" if policy_action in {"clarify", "answer_meta_then_redirect"} else "pressure_followup"

    action = _normalize_action(str(payload.get("action") or ""), default_action=default_action)
    question_text = _sanitize_question_text(str(payload.get("question_text") or ""))
    if not question_text or _is_repeated_question(question_text, ctx.asked_questions):
        question_text, sid, step = _pick_diversified_fallback_question(
            ctx=ctx,
            action=action,
            asked_questions=ctx.asked_questions,
        )
        payload.setdefault("scenario_id", sid)
        payload.setdefault("scenario_step", step)
    target_competency = str(payload.get("target_competency") or "").strip() or _pick_fallback_target_competency(ctx)
    raw_phase = str(payload.get("phase") or "").strip().lower()
    phase = raw_phase if raw_phase in _ALLOWED_PHASES else _infer_phase_from_action(action, state)
    scenario_id_raw = payload.get("scenario_id")
    scenario_id = str(scenario_id_raw).strip() if isinstance(scenario_id_raw, str) and scenario_id_raw.strip() else None
    scenario_step = max(0, _safe_int(payload.get("scenario_step"), 0 if scenario_id else 0))
    difficulty_tier = max(1, min(5, _safe_int(payload.get("difficulty_tier"), int(state.get("difficulty_tier") or 3))))
    reason = str(payload.get("reason") or "").strip() or "llm_decision_repaired"
    expected_signal = str(payload.get("expected_signal") or "").strip() or "concrete_skill_signal"
    conversational_intent = str(payload.get("conversational_intent") or "").strip().lower()
    if not conversational_intent:
        conversational_intent = _default_conversational_intent_from_action(action)
    information_target = str(payload.get("information_target") or "").strip() or target_competency
    return {
        "action": action,
        "question_text": question_text,
        "target_competency": target_competency,
        "phase": phase,
        "scenario_id": scenario_id,
        "scenario_step": scenario_step,
        "difficulty_tier": difficulty_tier,
        "reason": reason,
        "expected_signal": expected_signal,
        "conversational_intent": conversational_intent,
        "information_target": information_target,
    }


def _fallback_action_from_policy(policy_context: dict[str, Any]) -> str:
    policy_action = str(policy_context.get("policy_action") or "").strip().lower()
    if policy_action in {"clarify", "answer_meta_then_redirect"}:
        return "clarify"
    if policy_action in {"pressure_followup", "switch_topic"}:
        return "pressure_followup"
    if policy_action in _ALLOWED_ACTIONS:
        return policy_action
    return "clarify"


def _default_conversational_intent_from_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    mapping = {
        "ask_resume_followup": "extract_resume_case",
        "pressure_followup": "pressure_followup_detail",
        "clarify": "clarify_candidate_understanding",
        "answer_meta_then_redirect": "meta_redirect_to_skill_signal",
        "start_scenario": "start_role_scenario",
        "continue_scenario": "continue_role_scenario",
        "switch_topic": "switch_competency_topic",
        "close_interview": "close_interview",
    }
    return mapping.get(normalized, "clarify_candidate_understanding")


def parse_or_repair_reasoning_response(
    raw_text: str,
    policy_context: dict[str, Any],
    *,
    ctx: InterviewStrategistContext,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    diagnostics = {
        "strategist_raw_response": str(raw_text or ""),
        "strategist_json_valid": False,
        "strategist_repair_applied": False,
        "strategist_error_reason": "",
    }
    extracted = _extract_json_candidate(raw_text)
    if not extracted:
        diagnostics["strategist_error_reason"] = "empty_reasoning_response"
        return None, diagnostics
    try:
        payload = json.loads(extracted)
        if not isinstance(payload, dict):
            diagnostics["strategist_error_reason"] = "reasoning_json_not_object"
            return None, diagnostics
    except Exception as exc:
        diagnostics["strategist_error_reason"] = f"reasoning_json_parse_error:{exc}"
        return None, diagnostics

    repaired = dict(payload)
    defaults = {
        "candidate_understanding": "partial",
        "candidate_cooperation_level": "neutral",
        "conversation_problem": "none",
        "missing_signal": _pick_fallback_target_competency(ctx),
        "resume_evidence_status": "partial",
        "best_next_move": _fallback_action_from_policy(policy_context),
        "conversational_intent": _default_conversational_intent_from_action(
            _fallback_action_from_policy(policy_context)
        ),
        "information_target": "concrete_skill_signal",
        "question_goal": "collect one concrete skill signal",
        "question_style": "conversational",
        "why_this_move": "align with policy and current phase",
    }
    for key, default_value in defaults.items():
        value = repaired.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            repaired[key] = default_value
            diagnostics["strategist_repair_applied"] = True

    mapped_action = _map_reasoning_move_to_action(
        str(repaired.get("best_next_move") or ""),
        policy_context=policy_context,
    )
    if mapped_action != str(repaired.get("best_next_move") or ""):
        repaired["best_next_move"] = mapped_action
        diagnostics["strategist_repair_applied"] = True

    conversational_intent = str(repaired.get("conversational_intent") or "").strip().lower()
    if not conversational_intent:
        repaired["conversational_intent"] = _default_conversational_intent_from_action(mapped_action)
        diagnostics["strategist_repair_applied"] = True

    information_target = str(repaired.get("information_target") or "").strip()
    if not information_target:
        repaired["information_target"] = str(repaired.get("missing_signal") or "concrete_skill_signal")
        diagnostics["strategist_repair_applied"] = True

    style = str(repaired.get("question_style") or "").strip().lower()
    if style not in {"conversational", "probing", "simplified", "edge_case"}:
        repaired["question_style"] = "conversational"
        diagnostics["strategist_repair_applied"] = True

    diagnostics["strategist_json_valid"] = True
    return repaired, diagnostics


def parse_or_repair_question_phrasing_response(
    raw_text: str,
    *,
    ctx: InterviewStrategistContext,
    action: str,
) -> tuple[str | None, dict[str, Any]]:
    diagnostics = {
        "strategist_raw_response": str(raw_text or ""),
        "strategist_json_valid": False,
        "strategist_repair_applied": False,
        "strategist_error_reason": "",
    }
    extracted = _extract_json_candidate(raw_text)
    if not extracted:
        diagnostics["strategist_error_reason"] = "empty_phrase_response"
        return None, diagnostics
    try:
        payload = json.loads(extracted)
    except Exception:
        payload = {"question_text": extracted}
        diagnostics["strategist_repair_applied"] = True
    if not isinstance(payload, dict):
        diagnostics["strategist_error_reason"] = "phrase_json_not_object"
        return None, diagnostics

    question_text = _sanitize_question_text(str(payload.get("question_text") or ""))
    if not question_text:
        diagnostics["strategist_error_reason"] = "empty_question_text"
        return None, diagnostics
    if _is_repeated_question(question_text, ctx.asked_questions):
        diagnostics["strategist_error_reason"] = "repeated_question_text"
        question_text, _sid, _step = _pick_diversified_fallback_question(
            ctx=ctx,
            action=action,
            asked_questions=ctx.asked_questions,
        )
        diagnostics["strategist_repair_applied"] = True
    diagnostics["strategist_json_valid"] = True
    return question_text, diagnostics


def parse_or_repair_strategist_response(
    raw_text: str,
    policy_context: dict[str, Any],
    *,
    ctx: InterviewStrategistContext,
) -> tuple[QuestionDecision | None, dict[str, Any]]:
    diagnostics = {
        "strategist_raw_response": str(raw_text or ""),
        "strategist_json_valid": False,
        "strategist_repair_applied": False,
        "strategist_error_reason": "",
    }
    extracted = _extract_json_candidate(raw_text)
    if not extracted:
        diagnostics["strategist_error_reason"] = "empty_response"
        return None, diagnostics
    try:
        payload = json.loads(extracted)
        if not isinstance(payload, dict):
            diagnostics["strategist_error_reason"] = "json_not_object"
            return None, diagnostics
    except Exception as exc:
        diagnostics["strategist_error_reason"] = f"json_parse_error:{exc}"
        return None, diagnostics

    raw_action = str(payload.get("action") or "").strip().lower()
    normalized_action = _normalize_action(raw_action, default_action=_fallback_action_from_policy(policy_context))
    if raw_action != normalized_action:
        payload["action"] = normalized_action
        diagnostics["strategist_repair_applied"] = True
    repaired_payload = _repair_payload(payload, ctx=ctx, policy_context=policy_context)
    if repaired_payload != payload:
        diagnostics["strategist_repair_applied"] = True
    decision = _validate_question_decision_payload(repaired_payload, ctx)
    if not decision:
        diagnostics["strategist_error_reason"] = "payload_validation_failed_after_repair"
        return None, diagnostics
    diagnostics["strategist_json_valid"] = True
    return decision, diagnostics


def _validate_question_decision_payload(payload: dict[str, Any], ctx: InterviewStrategistContext) -> QuestionDecision | None:
    action = _normalize_action(
        str(payload.get("action") or "").strip(),
        default_action=_fallback_action_from_policy({"policy_action": ""}),
    )
    if action not in _ALLOWED_ACTIONS:
        return None

    question_text = _sanitize_question_text(str(payload.get("question_text") or ""))
    if not question_text:
        return None
    if _is_repeated_question(question_text, ctx.asked_questions):
        return None

    target_competency = str(payload.get("target_competency") or "").strip() or _pick_fallback_target_competency(ctx)
    state = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
    phase_raw = str(payload.get("phase") or "").strip().lower()
    phase = phase_raw if phase_raw in _ALLOWED_PHASES else _infer_phase_from_action(action, state)
    scenario_id_raw = payload.get("scenario_id")
    scenario_id = str(scenario_id_raw).strip() if isinstance(scenario_id_raw, str) and scenario_id_raw.strip() else None
    try:
        scenario_step_raw = payload.get("scenario_step", 0)
        if scenario_step_raw is None:
            scenario_step = 0
        else:
            scenario_step = max(0, int(scenario_step_raw))
    except Exception:
        scenario_step = 0
    try:
        difficulty_tier = int(payload.get("difficulty_tier", 3))
    except Exception:
        difficulty_tier = 3
    difficulty_tier = max(1, min(5, difficulty_tier))
    reason = str(payload.get("reason") or "").strip() or "llm_decision"
    expected_signal = str(payload.get("expected_signal") or "").strip() or "concrete_skill_signal"
    conversational_intent = str(payload.get("conversational_intent") or "").strip().lower()
    if not conversational_intent:
        conversational_intent = _default_conversational_intent_from_action(action)
    information_target = str(payload.get("information_target") or "").strip() or target_competency

    return QuestionDecision(
        action=action,  # type: ignore[arg-type]
        question_text=question_text,
        target_competency=target_competency,
        phase=phase,  # type: ignore[arg-type]
        scenario_id=scenario_id,
        scenario_step=scenario_step,
        difficulty_tier=difficulty_tier,
        reason=reason,
        expected_signal=expected_signal,
        conversational_intent=conversational_intent,
        information_target=information_target,
    )


class LLMInterviewStrategist:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "name", "unknown")

    async def _invoke_strategist(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict[str, Any]]:
        response = await self._provider.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        meta = {
            "provider": self.provider_name,
            "requested_model": response.requested_model,
            "actual_model_used": response.actual_model_used,
            "provider_attempts": response.provider_attempts,
            "provider_errors": response.provider_errors,
            "openrouter_fallback_used": bool(response.fallback_used),
        }
        return str(response.text or "").strip(), meta

    async def decide_next_interview_action(
        self,
        ctx: InterviewStrategistContext,
        model_override: str | None = None,
    ) -> QuestionDecision:
        resolved_model = resolve_llm_runtime_model(model_override)
        reasoning_messages = [
            {"role": "system", "content": _build_reasoning_system_prompt(ctx.language)},
            {
                "role": "user",
                "content": "Context JSON:\n" + json.dumps(_build_reasoning_context_payload(ctx), ensure_ascii=False),
            },
        ]
        policy_context = {
            "policy_action": str(
                ctx.policy_action
                or (ctx.last_answer_evaluation or {}).get("recommended_next_action")
                or ""
            ),
            "phase": str((ctx.interview_state_v2 or {}).get("phase") or ""),
        }
        strategist_reasoning_raw = ""
        strategist_phrase_raw = ""
        strategist_error_reason = ""
        strategist_retry_used = False
        strategist_provider_meta: dict[str, Any] = {
            "provider": self.provider_name,
            "requested_model": resolved_model,
            "actual_model_used": "",
            "provider_attempts": [],
            "provider_errors": [],
            "openrouter_fallback_used": False,
        }
        try:
            logger.info(
                "ai_model_call component=interview_strategist provider=%s model=%s role=%s",
                self.provider_name,
                resolved_model,
                ctx.role,
            )
            strategist_reasoning_raw, reasoning_meta = await self._invoke_strategist(
                model=resolved_model,
                messages=reasoning_messages,
                temperature=0.1,
                max_tokens=280,
            )
            strategist_provider_meta = reasoning_meta
            reasoning_payload, reasoning_diag = parse_or_repair_reasoning_response(
                strategist_reasoning_raw,
                policy_context,
                ctx=ctx,
            )
            strategist_error_reason = str(reasoning_diag.get("strategist_error_reason") or "")
            if not reasoning_payload:
                strategist_retry_used = True
                retry_reasoning_messages = [
                    {
                        "role": "system",
                        "content": "Return valid JSON only using this schema. No markdown, no explanation.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Schema:\n"
                            f"{_REASONING_SCHEMA_NOTE}\n\n"
                            "Context JSON:\n"
                            + json.dumps(_build_reasoning_context_payload(ctx), ensure_ascii=False)
                        ),
                    },
                ]
                retry_reasoning_raw, retry_reasoning_meta = await self._invoke_strategist(
                    model=resolved_model,
                    messages=retry_reasoning_messages,
                    temperature=0.1,
                    max_tokens=240,
                )
                strategist_provider_meta = retry_reasoning_meta
                strategist_reasoning_raw = retry_reasoning_raw or strategist_reasoning_raw
                reasoning_payload, retry_reasoning_diag = parse_or_repair_reasoning_response(
                    strategist_reasoning_raw,
                    policy_context,
                    ctx=ctx,
                )
                reasoning_diag = retry_reasoning_diag
                strategist_error_reason = str(retry_reasoning_diag.get("strategist_error_reason") or strategist_error_reason)

            if not reasoning_payload:
                raise ValueError(strategist_error_reason or "Invalid strategist JSON payload")

            action = _map_reasoning_move_to_action(
                str(reasoning_payload.get("best_next_move") or ""),
                policy_context=policy_context,
            )
            state = ctx.interview_state_v2 if isinstance(ctx.interview_state_v2, dict) else {}
            target_competency = str(reasoning_payload.get("missing_signal") or "").strip() or _pick_fallback_target_competency(ctx)
            phase = _infer_phase_from_action(action, state)
            scenario_id: str | None = None
            scenario_step = 0
            current_sid = str(state.get("current_scenario_id") or "").strip() or None
            current_step = max(0, _safe_int(state.get("scenario_step"), 0))
            if action in {"start_scenario", "continue_scenario"}:
                if action == "continue_scenario" and current_sid:
                    scenario_id = current_sid
                    scenario_step = current_step
                else:
                    _, fallback_sid, fallback_step = _pick_fallback_question(ctx)
                    scenario_id = fallback_sid or current_sid
                    scenario_step = max(0, int(fallback_step or current_step))

            base_difficulty = max(1, min(5, _safe_int(state.get("difficulty_tier"), 3)))
            quality = str((ctx.last_answer_evaluation or {}).get("quality") or "").strip().lower()
            style = str(reasoning_payload.get("question_style") or "").strip().lower()
            difficulty = base_difficulty
            if quality == "strong" and action in {"continue_scenario", "switch_topic"}:
                difficulty += 1
            if quality in {"weak", "no_signal"} or action in {"clarify", "ask_resume_followup"}:
                difficulty -= 1
            if style == "edge_case":
                difficulty += 1
            difficulty = max(1, min(5, difficulty))

            phrasing_input = {
                "role": ctx.role,
                "language": ctx.language,
                "action": action,
                "target_competency": target_competency,
                "phase": phase,
                "scenario_id": scenario_id,
                "scenario_step": scenario_step,
                "difficulty_tier": difficulty,
                "reasoning": reasoning_payload,
                "resume_summary": ctx.resume_summary,
                "last_question": ctx.last_question,
                "last_answer": ctx.last_answer,
                "asked_questions": ctx.asked_questions[-8:],
                "scenario_hint_question": _pick_fallback_question(ctx)[0],
            }
            phrasing_messages = [
                {"role": "system", "content": _build_question_phrasing_system_prompt(ctx.language)},
                {"role": "user", "content": "Input JSON:\n" + json.dumps(phrasing_input, ensure_ascii=False)},
            ]
            strategist_phrase_raw, phrase_meta = await self._invoke_strategist(
                model=resolved_model,
                messages=phrasing_messages,
                temperature=0.2,
                max_tokens=190,
            )
            strategist_provider_meta = phrase_meta
            question_text, phrase_diag = parse_or_repair_question_phrasing_response(
                strategist_phrase_raw,
                ctx=ctx,
                action=action,
            )
            strategist_error_reason = str(phrase_diag.get("strategist_error_reason") or strategist_error_reason)
            if not question_text:
                strategist_retry_used = True
                retry_phrasing_messages = [
                    {
                        "role": "system",
                        "content": "Return valid JSON only using this schema: {\"question_text\": \"string\"}.",
                    },
                    {"role": "user", "content": "Input JSON:\n" + json.dumps(phrasing_input, ensure_ascii=False)},
                ]
                retry_phrase_raw, retry_phrase_meta = await self._invoke_strategist(
                    model=resolved_model,
                    messages=retry_phrasing_messages,
                    temperature=0.1,
                    max_tokens=170,
                )
                strategist_provider_meta = retry_phrase_meta
                strategist_phrase_raw = retry_phrase_raw or strategist_phrase_raw
                question_text, retry_phrase_diag = parse_or_repair_question_phrasing_response(
                    strategist_phrase_raw,
                    ctx=ctx,
                    action=action,
                )
                phrase_diag = retry_phrase_diag
                strategist_error_reason = str(retry_phrase_diag.get("strategist_error_reason") or strategist_error_reason)

            if not question_text:
                raise ValueError(strategist_error_reason or "Invalid strategist question phrasing payload")

            payload = {
                "action": action,
                "question_text": question_text,
                "target_competency": target_competency,
                "phase": phase,
                "scenario_id": scenario_id,
                "scenario_step": scenario_step,
                "difficulty_tier": difficulty,
                "reason": str(reasoning_payload.get("why_this_move") or "reasoning_based_move"),
                "expected_signal": str(reasoning_payload.get("question_goal") or "concrete_skill_signal"),
                "conversational_intent": str(
                    reasoning_payload.get("conversational_intent")
                    or _default_conversational_intent_from_action(action)
                ),
                "information_target": str(
                    reasoning_payload.get("information_target")
                    or reasoning_payload.get("missing_signal")
                    or target_competency
                ),
            }
            repaired_payload = _repair_payload(payload, ctx=ctx, policy_context=policy_context)
            decision = _validate_question_decision_payload(repaired_payload, ctx)
            if not decision:
                raise ValueError("reasoning_payload_validation_failed")

            json_valid = bool(reasoning_diag.get("strategist_json_valid")) and bool(phrase_diag.get("strategist_json_valid"))
            if json_valid:
                strategist_error_reason = ""

            decision.strategist_raw_response = json.dumps(
                {
                    "reasoning_raw": strategist_reasoning_raw,
                    "phrasing_raw": strategist_phrase_raw,
                },
                ensure_ascii=False,
            )
            decision.strategist_json_valid = json_valid
            decision.strategist_repair_applied = bool(reasoning_diag.get("strategist_repair_applied")) or bool(
                phrase_diag.get("strategist_repair_applied")
            )
            decision.strategist_retry_used = strategist_retry_used
            decision.strategist_error_reason = strategist_error_reason
            decision.ai_provider = str(strategist_provider_meta.get("provider") or self.provider_name)
            decision.requested_model = str(strategist_provider_meta.get("requested_model") or resolved_model)
            decision.actual_model_used = str(strategist_provider_meta.get("actual_model_used") or resolved_model)
            decision.provider_attempts = list(strategist_provider_meta.get("provider_attempts") or [])
            decision.provider_errors = list(strategist_provider_meta.get("provider_errors") or [])
            decision.openrouter_fallback_used = bool(strategist_provider_meta.get("openrouter_fallback_used"))
            record_ai_success(
                component="interview_strategist",
                provider=decision.ai_provider or self.provider_name,
                model=decision.actual_model_used or resolved_model,
                note=("fallback_models_used" if decision.openrouter_fallback_used else None),
            )
            return decision
        except Exception as exc:
            record_ai_error(
                component="interview_strategist",
                provider=str(strategist_provider_meta.get("provider") or self.provider_name),
                model=resolved_model,
                error=str(exc),
            )
            logger.exception("Interview strategist fallback triggered")
            fallback = _fallback_decision(ctx, reason="deterministic_fallback_after_invalid_llm_json")
            fallback.strategist_raw_response = json.dumps(
                {
                    "reasoning_raw": strategist_reasoning_raw,
                    "phrasing_raw": strategist_phrase_raw,
                },
                ensure_ascii=False,
            )
            fallback.strategist_json_valid = False
            fallback.strategist_repair_applied = False
            fallback.strategist_retry_used = strategist_retry_used
            fallback.strategist_error_reason = str(exc)
            fallback.ai_provider = str(strategist_provider_meta.get("provider") or self.provider_name)
            fallback.requested_model = str(strategist_provider_meta.get("requested_model") or resolved_model)
            fallback.actual_model_used = str(strategist_provider_meta.get("actual_model_used") or "")
            fallback.provider_attempts = list(strategist_provider_meta.get("provider_attempts") or [])
            fallback.provider_errors = list(strategist_provider_meta.get("provider_errors") or [str(exc)])
            fallback.openrouter_fallback_used = bool(strategist_provider_meta.get("openrouter_fallback_used"))
            return fallback


class DeterministicInterviewStrategist:
    async def decide_next_interview_action(
        self,
        ctx: InterviewStrategistContext,
        model_override: str | None = None,
    ) -> QuestionDecision:
        _ = model_override
        return _fallback_decision(ctx, reason="deterministic_strategy_no_llm")


class DisabledInterviewStrategist:
    async def decide_next_interview_action(
        self,
        ctx: InterviewStrategistContext,
        model_override: str | None = None,
    ) -> QuestionDecision:
        _ = (ctx, model_override)
        raise RuntimeError("Interview strategist is not configured")


try:
    _provider = get_llm_provider(settings)
except Exception:
    _provider = None

if _provider and _provider.name not in {"mock"}:
    strategist: LLMInterviewStrategist | DeterministicInterviewStrategist | DisabledInterviewStrategist
    strategist = LLMInterviewStrategist(provider=_provider)
elif settings.allow_mock_ai:
    strategist = DeterministicInterviewStrategist()
else:
    strategist = DisabledInterviewStrategist()


async def decide_next_interview_action(ctx: InterviewStrategistContext) -> QuestionDecision:
    """Public entrypoint used by interview engine v2."""
    return await strategist.decide_next_interview_action(ctx)
