"""
Interview service — owns all interview business logic.
Routers call these functions; no SQLAlchemy queries in routers.

question_count is an explicit DB column on Interview, incremented here.
It is the authoritative source of truth — no need to re-count messages.
"""
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assessor import AssessmentResult, assessor
from app.ai.assessor import MockAssessor
from app.ai.competencies import (
    build_interview_plan,
    get_role_core_competency_order,
    get_role_question_blocks,
    get_role_scenario_chains,
)
from app.ai.interview_strategist import (
    InterviewStrategistContext,
    decide_next_interview_action,
)
from app.ai.interview_intents import classify_candidate_intent
from app.ai.interview_policy import decide_interview_policy
from app.ai.pressure_followup import (
    build_interviewer_redirect,
    build_pressure_followup,
)
from app.ai.runtime_status import get_ai_runtime_status, record_ai_error, record_ai_success
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.ai.interviewer import (
    MAX_QUESTIONS,
    InterviewContext,
    MockInterviewer,
    classify_answer,
    extract_mentioned_technologies,
    interviewer,
)
from app.ai.resume_profile import preprocess_resume
from app.models.candidate import Candidate
from app.models.interview import Interview, InterviewMessage
from app.models.report import AssessmentReport
from app.models.resume import Resume
from app.models.skill import CandidateSkill
from app.models.template import InterviewTemplate
from app.schemas.interview import (
    AssessmentProgressResponse,
    CodingTaskArtifactResponse,
    FinishInterviewResponse,
    InterviewDetailResponse,
    InterviewStageResponse,
    InterviewModuleSessionResponse,
    InterviewReportStatusResponse,
    InterviewMessageResponse,
    ProctoringTimelineResponse,
    InterviewReplayResponse,
    ReplayTurn,
    TranscriptBlockResponse,
    ReportSummary,
    SendMessageResponse,
    StartInterviewResponse,
    WrittenArtifactResponse,
)
from app.services.candidate_access_service import has_company_candidate_workspace_access
from app.services.platform_settings_service import build_effective_workspace_ai_settings


# ---------------------------------------------------------------------------
# Domain exceptions — routers translate these into HTTP responses
# ---------------------------------------------------------------------------

class NoActiveResumeError(Exception):
    """Candidate has no active resume — interview cannot start."""


class InterviewNotFoundError(Exception):
    """Interview does not exist or does not belong to this candidate."""


class InterviewNotActiveError(Exception):
    """Operation requires status=in_progress."""


class InterviewAlreadyFinishedError(Exception):
    """Interview has already been finished."""


class MaxQuestionsReachedError(Exception):
    """All questions answered — candidate must call /finish."""


class MaxQuestionsNotReachedError(Exception):
    """Cannot finish before all questions have been asked."""


class ReportRetryNotAllowedError(Exception):
    """Manual retry is not allowed for this interview state."""


class CodingTaskArtifactUnavailableError(Exception):
    """Operation requires a coding_task interview module."""


class WrittenArtifactUnavailableError(Exception):
    """Operation requires a written_communication interview module."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_INTERVIEW_STATE_V2_KEY = "interview_state_v2"
_RESUME_DEEP_DIVE_MAX_SCORED_TURNS = 4


def _is_interview_engine_v2_enabled(*, role: str | None = None) -> bool:
    if settings.interview_engine_version != "v2":
        return False
    v2_roles = settings.interview_engine_v2_roles
    if not v2_roles:
        return True
    normalized_role = str(role or "").strip().lower()
    return normalized_role in v2_roles


def _default_interview_state_v2(
    *,
    role: str,
    language: str,
) -> dict[str, Any]:
    return {
        "engine_version": "v2",
        "phase": "intro",
        "role": role,
        "language": language,
        "current_competency": None,
        "current_scenario_id": None,
        "scenario_step": 0,
        "attempts_on_current_step": 0,
        "confusion_count": 0,
        "repeated_question_count": 0,
        "semantic_repeated_question_count": 0,
        "covered_competencies": [],
        "validated_competencies": [],
        "weak_competencies": [],
        "asked_questions": [],
        "conversational_intent_history": [],
        "information_target_history": [],
        "last_answer_evaluation": None,
        "next_action": None,
        "resume_evidence": {
            "role_context": False,
            "concrete_case": False,
            "personal_actions": False,
            "result_or_impact": False,
            "resume_questions_count": 0,
        },
        "weak_answer_streak": 0,
        "no_case_streak": 0,
        "last_step_key": "",
        "current_step_key": "",
        "resume_scored_turns": 0,
        "last_policy_decision": None,
        "decision_traces": [],
        "interview_quality_metrics": _default_interview_quality_metrics(),
    }


def _merge_interview_state_v2_defaults(
    state_v2: dict[str, Any],
    *,
    role: str,
    language: str,
) -> dict[str, Any]:
    merged = _default_interview_state_v2(role=role, language=language)
    merged.update(state_v2)
    merged["engine_version"] = "v2"
    merged["role"] = str(merged.get("role") or role)
    merged["language"] = str(merged.get("language") or language)
    return merged


def get_interview_state_v2(interview: Interview) -> dict[str, Any]:
    raw_state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    raw_v2 = raw_state.get(_INTERVIEW_STATE_V2_KEY)
    if isinstance(raw_v2, dict):
        return _merge_interview_state_v2_defaults(
            raw_v2,
            role=interview.target_role,
            language=interview.language,
        )
    return _default_interview_state_v2(
        role=interview.target_role,
        language=interview.language,
    )


def update_interview_state_v2(
    interview: Interview,
    patch: dict[str, Any],
) -> dict[str, Any]:
    current = get_interview_state_v2(interview)
    current.update(patch or {})
    current = _merge_interview_state_v2_defaults(
        current,
        role=interview.target_role,
        language=interview.language,
    )
    full_state = dict(interview.interview_state or {})
    full_state[_INTERVIEW_STATE_V2_KEY] = current
    interview.interview_state = full_state
    return current


def _to_interview_state_v2_phase(
    *,
    topic_phase: str | None,
    question_type: str | None,
) -> str:
    normalized_phase = str(topic_phase or "").strip().lower()
    normalized_qtype = str(question_type or "").strip().lower()
    if normalized_phase == "intro":
        return "intro"
    if normalized_phase == "resume_followup":
        return "resume_deep_dive"
    if normalized_phase == "behavioral_closing":
        return "behavioral"
    if normalized_phase == "technical":
        if normalized_qtype in {"deep_technical", "edge_cases", "followup", "structured_reframe"}:
            return "technical_deep_dive"
        return "technical_case"
    return "intro"


def _normalize_resume_evidence(value: Any) -> dict[str, Any]:
    evidence = dict(value) if isinstance(value, dict) else {}
    return {
        "role_context": bool(evidence.get("role_context")),
        "concrete_case": bool(evidence.get("concrete_case")),
        "personal_actions": bool(evidence.get("personal_actions")),
        "result_or_impact": bool(evidence.get("result_or_impact")),
        "resume_questions_count": max(0, _safe_int(evidence.get("resume_questions_count"), 0)),
    }


def _is_resume_related_phase(topic_phase: str | None) -> bool:
    normalized = str(topic_phase or "").strip().lower()
    return normalized in {"intro", "resume_followup"}


def _update_resume_evidence(
    *,
    resume_evidence: dict[str, Any],
    answer: str,
    answer_evaluation: dict[str, Any],
    topic_phase: str | None,
) -> dict[str, Any]:
    updated = _normalize_resume_evidence(resume_evidence)
    normalized_answer = " ".join((answer or "").strip().lower().split())
    if _is_resume_related_phase(topic_phase):
        updated["resume_questions_count"] = max(0, int(updated.get("resume_questions_count", 0))) + 1

    words = normalized_answer.split()
    role_context_markers = (
        "работаю",
        "позици",
        "роль",
        "отвечал",
        "руковод",
        "рук ",
        "рук.",
        "направления",
        "сопровожд",
        "engineer",
        "manager",
        "lead",
        "responsib",
    )
    concrete_case_markers = (
        "кейс",
        "например",
        "когда",
        "инцидент",
        "дефект",
        "ошибк",
        "релиз",
        "case",
        "incident",
        "issue",
        "when",
    )
    if len(words) >= 4 and any(marker in normalized_answer for marker in role_context_markers):
        updated["role_context"] = True
    if any(marker in normalized_answer for marker in concrete_case_markers):
        updated["concrete_case"] = True
    personal_action_markers = (
        "я анализ",
        "я воспроизв",
        "я провер",
        "я делал",
        "я тестир",
        "я монитор",
        "я организ",
        "мы делал",
        "мы тестир",
        "мы анализир",
        "я настро",
        "я собрал",
        "я наш",
        "я запуст",
    )
    result_markers = (
        "сниз",
        "повыс",
        "улучш",
        "ускор",
        "принял на сопровожд",
        "не повторял",
        "стало лучше",
        "стало стабиль",
        "стало быстрее",
        "%",
    )
    if bool(answer_evaluation.get("has_personal_action")) or any(
        marker in normalized_answer for marker in personal_action_markers
    ):
        updated["personal_actions"] = True
    if bool(answer_evaluation.get("has_result")) or any(marker in normalized_answer for marker in result_markers):
        updated["result_or_impact"] = True
    return updated


def _resume_evidence_score(resume_evidence: dict[str, Any]) -> int:
    evidence = _normalize_resume_evidence(resume_evidence)
    return sum(
        1
        for key in ("role_context", "concrete_case", "personal_actions", "result_or_impact")
        if bool(evidence.get(key))
    )


def _resume_deep_dive_gate_opened(resume_evidence: dict[str, Any]) -> bool:
    evidence = _normalize_resume_evidence(resume_evidence)
    return (
        bool(evidence.get("role_context"))
        and bool(evidence.get("concrete_case"))
        and bool(evidence.get("personal_actions"))
    )


def _resume_deep_dive_force_transition(
    *,
    resume_scored_turns: int,
) -> bool:
    return max(0, int(resume_scored_turns)) >= _RESUME_DEEP_DIVE_MAX_SCORED_TURNS


def _build_resume_deep_dive_followup(
    *,
    language: str,
    resume_evidence: dict[str, Any],
    resume_context: str | None,
) -> str:
    is_en = str(language).lower().startswith("en")
    evidence = _normalize_resume_evidence(resume_evidence)
    context_hint = str(resume_context or "").strip()
    if not context_hint:
        context_hint = (
            "вашему опыту в сопровождении/тестировании"
            if not is_en
            else "your support/testing experience"
        )
    if not evidence.get("concrete_case"):
        return (
            f"Ок, давайте по вашему опыту ({context_hint}): разберите один конкретный рабочий кейс — что произошло?"
            if not is_en
            else f"Okay, using your context ({context_hint}), walk through one concrete work case — what happened?"
        )
    if not evidence.get("personal_actions"):
        return (
            "В этом кейсе что именно сделали лично вы: 2-3 шага по порядку?"
            if not is_en
            else "In that case, what exactly did you do personally: 2-3 steps in order?"
        )
    if not evidence.get("result_or_impact"):
        return (
            "Какой измеримый результат получили: что стало лучше и чем это подтвердили?"
            if not is_en
            else "What measurable result did you get: what improved and how did you validate it?"
        )
    return (
        "Давайте закрепим по вашему опыту: один короткий кейс в формате контекст → ваши действия → результат."
        if not is_en
        else "Let's anchor this to your experience: one short case in context → your actions → result format."
    )


def _compact_answer_evaluation_for_trace(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    payload = evaluation or {}
    return {
        "quality": str(payload.get("quality") or ""),
        "answer_score": float(payload.get("answer_score") or 0),
        "recommended_next_action": str(payload.get("recommended_next_action") or ""),
        "has_concrete_example": bool(payload.get("has_concrete_example")),
        "has_personal_action": bool(payload.get("has_personal_action")),
        "has_technical_detail": bool(payload.get("has_technical_detail")),
        "has_result": bool(payload.get("has_result")),
        "candidate_confusion": bool(payload.get("candidate_confusion")),
        "candidate_asks_clarification": bool(payload.get("candidate_asks_clarification")),
    }


def _derive_conversational_intent(
    *,
    raw_intent: str | None,
    action: str | None,
    phase: str | None,
) -> str:
    normalized = str(raw_intent or "").strip().lower()
    if normalized:
        return normalized
    action_key = str(action or "").strip().lower()
    phase_key = str(phase or "").strip().lower()
    if action_key == "ask_resume_followup":
        if phase_key in {"intro", "resume_deep_dive"}:
            return "extract_resume_case"
        return "resume_followup"
    if action_key == "pressure_followup":
        return "pressure_followup_detail"
    if action_key == "clarify":
        return "clarify_candidate_understanding"
    if action_key == "answer_meta_then_redirect":
        return "meta_redirect_to_skill_signal"
    if action_key == "start_scenario":
        return "start_role_scenario"
    if action_key == "continue_scenario":
        return "continue_role_scenario"
    if action_key == "switch_topic":
        return "switch_competency_topic"
    if action_key == "close_interview":
        return "close_interview"
    return "unknown_intent"


def _conversational_intent_streak(intent_history: list[str], current_intent: str) -> int:
    normalized_current = str(current_intent or "").strip().lower()
    if not normalized_current:
        return 0
    streak = 1
    for value in reversed(intent_history[-8:]):
        normalized_value = str(value or "").strip().lower()
        if normalized_value != normalized_current:
            break
        streak += 1
    return streak


def _semantic_anti_loop_adaptation(
    *,
    role: str,
    language: str,
    current_question: str,
    candidate_answer: str,
    competency: str,
    scenario_context: str,
    resume_evidence: dict[str, Any],
    answer_evaluation: dict[str, Any],
) -> tuple[str, str, str]:
    is_en = str(language).lower().startswith("en")
    evidence = _normalize_resume_evidence(resume_evidence)
    if not evidence.get("personal_actions"):
        question = (
            "Окей, давайте по шагам: что именно сделали вы лично в этом кейсе? Назовите 2-3 действия по порядку."
            if not is_en
            else "Okay, step by step: what exactly did you do personally in that case? Name 2-3 actions in order."
        )
        return question, "extract_personal_actions", "personal_actions"
    if not evidence.get("result_or_impact"):
        question = (
            "Как вы поняли, что решение сработало: какой результат получили и чем это подтвердили?"
            if not is_en
            else "How did you confirm the solution worked: what result did you get and how did you validate it?"
        )
        return question, "extract_result_impact", "result_or_impact"

    concrete_case = build_pressure_followup(
        role=role,
        current_question=current_question,
        candidate_answer=candidate_answer,
        competency=competency,
        scenario_context=scenario_context,
        language=language,
        answer_evaluation=answer_evaluation,
        force_concrete_example=True,
    )
    return concrete_case, "provide_concrete_scenario", "concrete_incident"


def _append_v2_decision_trace(
    traces: list[dict[str, Any]],
    trace: dict[str, Any],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    normalized = list(traces or [])
    normalized.append(trace)
    return normalized[-limit:]


def _default_interview_quality_metrics() -> dict[str, int]:
    return {
        "total_turns": 0,
        "scored_questions": 0,
        "strategist_success_count": 0,
        "fallback_count": 0,
        "repeated_question_count": 0,
        "semantic_repeated_question_count": 0,
        "resume_phase_turns": 0,
        "technical_case_turns": 0,
        "pressure_followup_count": 0,
        "clarification_count": 0,
    }


def _normalize_interview_quality_metrics(value: Any) -> dict[str, int]:
    defaults = _default_interview_quality_metrics()
    payload = dict(value) if isinstance(value, dict) else {}
    normalized: dict[str, int] = {}
    for key, default in defaults.items():
        normalized[key] = max(0, _safe_int(payload.get(key), default))
    return normalized


def _update_interview_quality_metrics(
    *,
    metrics: dict[str, int],
    trace: dict[str, Any] | None,
    should_count_as_answer: bool,
    phase_after: str | None,
    policy_action: str | None,
) -> dict[str, int]:
    updated = _normalize_interview_quality_metrics(metrics)
    updated["total_turns"] += 1
    if should_count_as_answer:
        updated["scored_questions"] += 1

    trace_payload = trace or {}
    selected_generator = str(trace_payload.get("selected_generator") or "").strip().lower()
    strategist_json_valid = bool(trace_payload.get("strategist_json_valid"))
    if selected_generator == "strategist" and strategist_json_valid:
        updated["strategist_success_count"] += 1
    elif selected_generator in {"fallback", "legacy_v1", "legacy_v1_override"} or (
        selected_generator == "strategist" and not strategist_json_valid
    ):
        updated["fallback_count"] += 1

    if bool(trace_payload.get("was_question_rejected_as_repeated")):
        updated["repeated_question_count"] += 1
    if bool(trace_payload.get("semantic_repeat_detected")):
        updated["semantic_repeated_question_count"] += 1

    phase = str(phase_after or trace_payload.get("current_phase_after") or "").strip().lower()
    if phase == "resume_deep_dive":
        updated["resume_phase_turns"] += 1
    if phase == "technical_case":
        updated["technical_case_turns"] += 1

    normalized_policy_action = str(policy_action or trace_payload.get("policy_action") or "").strip().lower()
    if normalized_policy_action == "pressure_followup" or selected_generator == "pressure_followup":
        updated["pressure_followup_count"] += 1
    if normalized_policy_action in {"clarify", "answer_meta_then_redirect"}:
        updated["clarification_count"] += 1

    return updated


def _build_live_smoke_summary(metrics: dict[str, int]) -> str:
    payload = _normalize_interview_quality_metrics(metrics)
    return (
        "Live-smoke summary: "
        f"turns={payload['total_turns']}, "
        f"scored={payload['scored_questions']}, "
        f"strategist_success={payload['strategist_success_count']}, "
        f"fallbacks={payload['fallback_count']}, "
        f"repeats={payload['repeated_question_count']}, "
        f"semantic_repeats={payload['semantic_repeated_question_count']}, "
        f"resume_turns={payload['resume_phase_turns']}, "
        f"technical_turns={payload['technical_case_turns']}, "
        f"pressure_followups={payload['pressure_followup_count']}, "
        f"clarifications={payload['clarification_count']}."
    )

async def _get_interview(
    db: AsyncSession,
    interview_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> Interview:
    interview = await db.scalar(
        select(Interview).where(
            Interview.id == interview_id,
            Interview.candidate_id == candidate_id,
        )
    )
    if not interview:
        raise InterviewNotFoundError()
    return interview


async def _get_messages(db: AsyncSession, interview_id: uuid.UUID) -> list[InterviewMessage]:
    result = await db.scalars(
        select(InterviewMessage)
        .where(InterviewMessage.interview_id == interview_id)
        .order_by(InterviewMessage.created_at)
    )
    return list(result)


def _build_progress_counters(
    *,
    core_question_count: int,
    messages: list[InterviewMessage],
) -> dict[str, int]:
    asked_questions_count = sum(1 for message in messages if message.role == "assistant")
    answered_questions_count = sum(1 for message in messages if message.role == "candidate")
    return {
        "core_question_count": max(core_question_count, 0),
        "asked_questions_count": max(asked_questions_count, 0),
        "answered_questions_count": max(answered_questions_count, 0),
    }


async def _get_assessment_progress(
    db: AsyncSession,
    interview: Interview,
) -> AssessmentProgressResponse | None:
    if not interview.company_assessment_id:
        return None

    from app.models.company_assessment import CompanyAssessment
    from app.services.assessment_invite_service import build_assessment_progress_payload

    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.id == interview.company_assessment_id)
    )
    if not assessment:
        return None
    return AssessmentProgressResponse(
        **build_assessment_progress_payload(
            assessment,
            interview_id=interview.id,
        )
    )


_SYSTEM_DESIGN_MODULE_TYPE = "system_design"
_BEHAVIORAL_INTERVIEW_MODULE_TYPE = "behavioral_interview"
_CODING_TASK_MODULE_TYPE = "coding_task"
_SQL_LIVE_MODULE_TYPE = "sql_live"
_WRITTEN_COMMUNICATION_MODULE_TYPE = "written_communication"
_SYSTEM_DESIGN_STAGE_KEYS = (
    "requirements",
    "high_level_design",
    "tradeoffs",
)
_BEHAVIORAL_INTERVIEW_STAGE_KEYS = (
    "ownership",
    "collaboration",
    "leadership",
    "reflection",
)
_CODING_TASK_STAGE_KEYS = (
    "task_brief",
    "implementation",
    "review",
)
_SQL_LIVE_STAGE_KEYS = (
    "schema_review",
    "query_authoring",
    "result_review",
)
_WRITTEN_COMMUNICATION_STAGE_KEYS = (
    "brief_alignment",
    "drafting",
    "editing",
)
_SYSTEM_DESIGN_SCENARIOS: dict[str, dict[str, str]] = {
    "backend_engineer": {
        "scenario_id": "multi_tenant_notifications",
        "title_en": "a multi-tenant notification platform",
        "title_ru": "multi-tenant платформу уведомлений",
        "prompt_en": "Design a service that sends email, push, and in-app notifications for multiple products with per-tenant rules, retries, and analytics.",
        "prompt_ru": "Спроектируйте сервис, который отправляет email, push и in-app уведомления для нескольких продуктов с tenant-правилами, retry и аналитикой.",
    },
    "frontend_engineer": {
        "scenario_id": "realtime_ops_dashboard",
        "title_en": "a real-time operations dashboard",
        "title_ru": "real-time operations dashboard",
        "prompt_en": "Design a browser-based dashboard that shows live metrics, incident timelines, filters, and role-based actions for hundreds of concurrent users.",
        "prompt_ru": "Спроектируйте browser-based dashboard с live-метриками, incident timeline, фильтрами и role-based actions для сотен одновременных пользователей.",
    },
    "qa_engineer": {
        "scenario_id": "test_orchestration_platform",
        "title_en": "a distributed test orchestration platform",
        "title_ru": "распределённую платформу оркестрации тестов",
        "prompt_en": "Design a platform that schedules automated test suites across parallel workers, stores artifacts, and surfaces flaky test diagnostics.",
        "prompt_ru": "Спроектируйте платформу, которая распределяет automated test suites по параллельным воркерам, хранит артефакты и показывает диагностику flaky tests.",
    },
    "devops_engineer": {
        "scenario_id": "multi_region_deploy_control_plane",
        "title_en": "a multi-region deployment control plane",
        "title_ru": "multi-region control plane для деплоев",
        "prompt_en": "Design a control plane that deploys services across regions, tracks rollouts, enforces approvals, and supports safe rollback.",
        "prompt_ru": "Спроектируйте control plane, который выкатывает сервисы по регионам, отслеживает rollout, применяет approvals и поддерживает безопасный rollback.",
    },
    "data_scientist": {
        "scenario_id": "real_time_fraud_scoring",
        "title_en": "a real-time fraud scoring system",
        "title_ru": "real-time систему fraud scoring",
        "prompt_en": "Design a system that scores transactions in real time, combines model outputs with rules, supports feature freshness, and enables analyst review.",
        "prompt_ru": "Спроектируйте систему, которая в real time оценивает транзакции, объединяет model outputs с правилами, поддерживает свежесть фичей и review аналитиком.",
    },
    "product_manager": {
        "scenario_id": "cross_team_experimentation_platform",
        "title_en": "a cross-team experimentation platform",
        "title_ru": "кросс-командную платформу экспериментов",
        "prompt_en": "Design a platform that lets teams configure experiments, define guardrail metrics, review results, and roll out changes safely.",
        "prompt_ru": "Спроектируйте платформу, где команды настраивают эксперименты, задают guardrail-метрики, анализируют результаты и безопасно раскатывают изменения.",
    },
    "mobile_engineer": {
        "scenario_id": "offline_first_mobile_sync",
        "title_en": "an offline-first mobile sync system",
        "title_ru": "offline-first систему синхронизации для mobile",
        "prompt_en": "Design a mobile sync architecture that works offline, resolves conflicts, batches updates, and protects battery usage.",
        "prompt_ru": "Спроектируйте mobile-архитектуру синхронизации, которая работает offline, разрешает конфликты, батчит обновления и бережёт батарею.",
    },
    "designer": {
        "scenario_id": "design_system_delivery_platform",
        "title_en": "a design system delivery platform",
        "title_ru": "платформу доставки design system",
        "prompt_en": "Design a platform that distributes design tokens, component guidance, versioned patterns, and feedback loops across product teams.",
        "prompt_ru": "Спроектируйте платформу, которая распространяет design tokens, component guidance, versioned patterns и feedback loops между продуктами.",
    },
}
_SYSTEM_DESIGN_DEFAULT_SCENARIO = {
    "scenario_id": "shared_internal_platform",
    "title_en": "a shared internal platform",
    "title_ru": "общую внутреннюю платформу",
    "prompt_en": "Design a shared platform used by multiple internal teams with role-based access, observability, and reliability constraints.",
    "prompt_ru": "Спроектируйте общую платформу для нескольких внутренних команд с role-based access, observability и требованиями к надёжности.",
}
_BEHAVIORAL_INTERVIEW_SCENARIOS: dict[str, dict[str, str]] = {
    "backend_engineer": {
        "scenario_id": "production_incident_ownership",
        "title_en": "a production incident ownership discussion",
        "title_ru": "разбор ownership в production-инциденте",
        "prompt_en": "Use concrete examples about taking ownership during a production incident, coordinating across teams, influencing the response, and reflecting on what changed afterward.",
        "prompt_ru": "Опирайтесь на конкретные примеры про ownership во время production-инцидента, координацию между командами, влияние на ход реакции и выводы о том, что изменилось после него.",
    },
    "frontend_engineer": {
        "scenario_id": "cross_team_delivery_conflict",
        "title_en": "a cross-team delivery conflict",
        "title_ru": "кросс-командный конфликт вокруг релиза",
        "prompt_en": "Use concrete examples about navigating delivery pressure, aligning with design and product, pushing back constructively, and improving collaboration after the conflict.",
        "prompt_ru": "Опирайтесь на конкретные примеры про давление дедлайна, выравнивание с design и product, конструктивный pushback и то, как вы улучшили взаимодействие после конфликта.",
    },
    "qa_engineer": {
        "scenario_id": "release_risk_escalation",
        "title_en": "a release-risk escalation",
        "title_ru": "эскалация релизного риска",
        "prompt_en": "Use concrete examples about escalating release risk, influencing the final decision, managing disagreement with delivery stakeholders, and learning from the outcome.",
        "prompt_ru": "Опирайтесь на конкретные примеры про эскалацию релизного риска, влияние на итоговое решение, работу с несогласием delivery-стейкхолдеров и выводы по итогам ситуации.",
    },
    "devops_engineer": {
        "scenario_id": "oncall_pressure_alignment",
        "title_en": "an on-call pressure alignment case",
        "title_ru": "кейс выравнивания под on-call давлением",
        "prompt_en": "Use concrete examples about incident pressure, operational ownership, cross-functional coordination, and the choices you made when time and reliability were both constrained.",
        "prompt_ru": "Опирайтесь на конкретные примеры про инцидентное давление, операционный ownership, кросс-функциональную координацию и решения, которые вы принимали при одновременном дефиците времени и требований к надёжности.",
    },
    "data_scientist": {
        "scenario_id": "experiment_tradeoff_discussion",
        "title_en": "an experiment trade-off discussion",
        "title_ru": "обсуждение trade-off по эксперименту",
        "prompt_en": "Use concrete examples about defending an evidence-based recommendation, aligning product and business stakeholders, handling disagreement, and reflecting on a miss or revision.",
        "prompt_ru": "Опирайтесь на конкретные примеры про защиту data-driven рекомендации, выравнивание product и business-стейкхолдеров, работу с несогласием и рефлексию над ошибкой или пересмотром решения.",
    },
    "product_manager": {
        "scenario_id": "stakeholder_priority_reset",
        "title_en": "a stakeholder priority reset",
        "title_ru": "пересборка приоритетов со стейкхолдерами",
        "prompt_en": "Use concrete examples about resetting priorities under pressure, aligning engineering and business stakeholders, leading without formal authority, and learning from a difficult call.",
        "prompt_ru": "Опирайтесь на конкретные примеры про пересборку приоритетов под давлением, выравнивание engineering и business-стейкхолдеров, лидерство без формальной власти и уроки из сложного решения.",
    },
    "mobile_engineer": {
        "scenario_id": "mobile_hotfix_coordination",
        "title_en": "a mobile hotfix coordination case",
        "title_ru": "координация mobile hotfix",
        "prompt_en": "Use concrete examples about handling crash pressure, coordinating with support and product, influencing the rollout plan, and reflecting on what you would change next time.",
        "prompt_ru": "Опирайтесь на конкретные примеры про давление из-за mobile-crash, координацию с support и product, влияние на rollout plan и рефлексию о том, что вы бы изменили в следующий раз.",
    },
    "designer": {
        "scenario_id": "design_feedback_conflict",
        "title_en": "a design feedback conflict",
        "title_ru": "конфликт вокруг design-feedback",
        "prompt_en": "Use concrete examples about balancing user advocacy with stakeholder pressure, collaborating through disagreement, influencing the final direction, and learning from the outcome.",
        "prompt_ru": "Опирайтесь на конкретные примеры про баланс между user advocacy и давлением стейкхолдеров, работу через конфликт, влияние на итоговое направление и выводы по итогам ситуации.",
    },
}
_BEHAVIORAL_INTERVIEW_DEFAULT_SCENARIO = {
    "scenario_id": "cross_functional_pressure_case",
    "title_en": "a cross-functional pressure case",
    "title_ru": "кейс кросс-функционального давления",
    "prompt_en": "Use concrete examples about ownership, collaboration, influence, and reflection in a high-pressure cross-functional situation.",
    "prompt_ru": "Опирайтесь на конкретные примеры про ownership, collaboration, влияние и рефлексию в напряжённой кросс-функциональной ситуации.",
}
_CODING_TASK_SCENARIOS: dict[str, dict[str, str]] = {
    "backend_engineer": {
        "scenario_id": "rate_limiter_window_counter",
        "title_en": "a FastAPI-friendly request rate limiter",
        "title_ru": "FastAPI-friendly лимитер запросов",
        "prompt_en": "Implement the core logic for a per-user sliding-window rate limiter that could sit behind a FastAPI endpoint or middleware. You can write a free-form solution: full code, partial code, helpers, or pseudocode, but show the important function boundaries, data structures, and test approach.",
        "prompt_ru": "Реализуйте core logic для per-user sliding-window rate limiter, который можно встроить в FastAPI endpoint или middleware. Можно писать в свободной форме: полный код, часть кода, helper-функции или псевдокод, но покажите ключевые границы функций, структуры данных и подход к тестированию.",
        "stack_focus_en": "Python, FastAPI, async service boundaries, and backend reliability",
        "stack_focus_ru": "Python, FastAPI, async service boundaries и backend reliability",
        "preferred_language": "python",
        "workspace_hint_en": "A free-form backend solution is acceptable. Focus on handler/service boundaries, validation, storage choices, and how the code would fit into a FastAPI codebase.",
        "workspace_hint_ru": "Подойдёт свободное backend-решение. Сделайте акцент на границах handler/service, валидации, выборе хранилища и том, как код встроится в FastAPI-кодовую базу.",
    },
    "frontend_engineer": {
        "scenario_id": "async_search_state_manager",
        "title_en": "a React async search state manager",
        "title_ru": "React-менеджер состояния async-поиска",
        "prompt_en": "Implement the core logic for a debounced async search state manager that could power a React component or hook. You can answer in free form, but show how you would structure state, cancellation, stale-response protection, and loading/error UX.",
        "prompt_ru": "Реализуйте core logic для debounced async search state manager, который мог бы лежать внутри React component или hook. Можно отвечать в свободной форме, но покажите, как вы структурируете state, cancelation, защиту от stale responses и loading/error UX.",
        "stack_focus_en": "React, TypeScript, state management, and resilient frontend UX",
        "stack_focus_ru": "React, TypeScript, state management и устойчивый frontend UX",
        "preferred_language": "typescript",
        "workspace_hint_en": "A free-form frontend solution is acceptable. Focus on hooks/components, async state transitions, cancellation, and how the UI avoids stale or broken states.",
        "workspace_hint_ru": "Подойдёт свободное frontend-решение. Сделайте акцент на hooks/components, async state transitions, cancelation и том, как UI избегает stale или broken states.",
    },
    "qa_engineer": {
        "scenario_id": "flaky_test_classifier",
        "title_en": "a flaky test classifier",
        "title_ru": "классификатор flaky-тестов",
        "prompt_en": "Implement logic that groups repeated test runs, detects flaky failures, and emits a stable summary for CI diagnostics. Free-form solutions are fine, but show test strategy, assertions, and the structure you would use in a QA automation codebase.",
        "prompt_ru": "Реализуйте логику, которая группирует повторные прогоны тестов, выявляет flaky failures и формирует стабильную сводку для CI-диагностики. Свободная форма ответа подходит, но покажите test strategy, assertions и структуру, которую вы бы использовали в QA automation codebase.",
        "stack_focus_en": "QA automation, pytest/playwright-style test strategy, and flaky-test diagnostics",
        "stack_focus_ru": "QA automation, pytest/playwright-style test strategy и flaky-test diagnostics",
        "preferred_language": "python",
        "workspace_hint_en": "A free-form QA solution is acceptable. Show how you would model failures, assertions, fixtures, reporting, or CI diagnostics instead of only describing the idea at a high level.",
        "workspace_hint_ru": "Подойдёт свободное QA-решение. Покажите, как вы моделируете failures, assertions, fixtures, reporting или CI diagnostics, а не только общую идею.",
    },
    "devops_engineer": {
        "scenario_id": "deployment_rollout_guard",
        "title_en": "a deployment rollout guard",
        "title_ru": "guard для rollout-деплоя",
        "prompt_en": "Implement logic that evaluates service rollout health from metrics/events and decides whether to continue, pause, or roll back deployment. Free-form code, config snippets, or structured pseudocode are fine, but show the operational decision rules clearly.",
        "prompt_ru": "Реализуйте логику, которая по метрикам и событиям rollout оценивает здоровье сервиса и решает: продолжать, поставить на паузу или откатить деплой. Подойдут свободный код, config snippets или структурированный псевдокод, но decision rules должны быть выражены явно.",
        "stack_focus_en": "Deployment automation, metrics-driven decisions, and ops safety controls",
        "stack_focus_ru": "Deployment automation, metrics-driven decisions и ops safety controls",
        "preferred_language": "python",
        "workspace_hint_en": "A free-form DevOps solution is acceptable. Show rollback thresholds, health checks, event inputs, and how the logic would fit into automation or control-plane code.",
        "workspace_hint_ru": "Подойдёт свободное DevOps-решение. Покажите rollback thresholds, health checks, входные события и то, как логика встроится в automation или control-plane code.",
    },
    "data_scientist": {
        "scenario_id": "feature_freshness_monitor",
        "title_en": "a feature freshness monitor",
        "title_ru": "монитор свежести фичей",
        "prompt_en": "Implement logic that validates feature freshness for scoring requests, applies fallbacks, and explains why a record should be blocked or allowed. Free-form code or structured pseudocode is fine, but show the data checks, thresholds, and decision path clearly.",
        "prompt_ru": "Реализуйте логику, которая проверяет свежесть фичей для scoring-запросов, применяет fallback и объясняет, почему запись нужно заблокировать или пропустить. Подойдут свободный код или структурированный псевдокод, но clearly покажите data checks, thresholds и decision path.",
        "stack_focus_en": "Python data logic, feature validation, and scoring pipeline safeguards",
        "stack_focus_ru": "Python data logic, feature validation и safeguards для scoring pipeline",
        "preferred_language": "python",
        "workspace_hint_en": "A free-form data solution is acceptable. Show thresholds, null/fallback handling, and how the logic would fit into a scoring or feature-serving pipeline.",
        "workspace_hint_ru": "Подойдёт свободное data-решение. Покажите thresholds, обработку null/fallback и то, как логика встроится в scoring или feature-serving pipeline.",
    },
    "product_manager": {
        "scenario_id": "experiment_guardrail_parser",
        "title_en": "an experiment guardrail parser",
        "title_ru": "парсер guardrail-метрик эксперимента",
        "prompt_en": "Implement logic that validates experiment guardrail metrics, flags invalid inputs, and produces a rollout recommendation payload for decision makers. Free-form pseudo-code or structured logic is fine if it clearly shows decision rules and output shape.",
        "prompt_ru": "Реализуйте логику, которая валидирует guardrail-метрики эксперимента, флагирует некорректные входы и формирует payload с рекомендацией по rollout. Свободный псевдокод или структурированная логика подходят, если в них чётко видны decision rules и форма результата.",
        "stack_focus_en": "Product analytics logic, rollout rules, and structured decision payloads",
        "stack_focus_ru": "Product analytics logic, rollout rules и structured decision payloads",
        "preferred_language": "other",
        "workspace_hint_en": "A free-form solution is acceptable. Prioritize clear business rules, input validation, and the final recommendation payload over exact syntax.",
        "workspace_hint_ru": "Подойдёт свободное решение. Приоритет: понятные бизнес-правила, input validation и итоговый recommendation payload, а не точный синтаксис.",
    },
    "mobile_engineer": {
        "scenario_id": "offline_sync_queue",
        "title_en": "an offline sync queue",
        "title_ru": "offline sync queue",
        "prompt_en": "Implement the core queue logic for offline sync with retries, conflict markers, and battery-friendly batching. Free-form code or structured pseudocode is fine, but show state transitions and failure handling clearly.",
        "prompt_ru": "Реализуйте core logic очереди offline sync с retry, conflict markers и батчингом, который бережёт батарею. Подойдут свободный код или структурированный псевдокод, но state transitions и failure handling должны быть выражены явно.",
        "stack_focus_en": "Mobile sync state, retries, conflicts, and battery-aware batching",
        "stack_focus_ru": "Mobile sync state, retries, conflicts и battery-aware batching",
        "preferred_language": "kotlin",
        "workspace_hint_en": "A free-form mobile solution is acceptable. Show queue state, retry policy, conflict markers, and how the logic behaves offline and after reconnect.",
        "workspace_hint_ru": "Подойдёт свободное mobile-решение. Покажите состояние очереди, retry policy, conflict markers и поведение offline и после reconnect.",
    },
    "designer": {
        "scenario_id": "design_token_transformer",
        "title_en": "a design token transformer",
        "title_ru": "трансформер design tokens",
        "prompt_en": "Implement logic that transforms design tokens into platform-specific output, validates required fields, and surfaces actionable errors. Free-form code or structured transformation rules are fine if the output shape is clear.",
        "prompt_ru": "Реализуйте логику, которая преобразует design tokens в platform-specific output, валидирует обязательные поля и возвращает понятные ошибки. Подойдут свободный код или структурированные правила трансформации, если форма результата остаётся понятной.",
        "stack_focus_en": "Design systems, token transforms, and platform handoff logic",
        "stack_focus_ru": "Design systems, token transforms и platform handoff logic",
        "preferred_language": "javascript",
        "workspace_hint_en": "A free-form design-systems solution is acceptable. Show token schema, validation rules, and how outputs are produced for different platforms.",
        "workspace_hint_ru": "Подойдёт свободное design-systems решение. Покажите схему токенов, правила валидации и то, как формируются outputs для разных платформ.",
    },
}
_CODING_TASK_DEFAULT_SCENARIO = {
    "scenario_id": "structured_business_rule_engine",
    "title_en": "a structured business-rule evaluator",
    "title_ru": "структурированный rule evaluator",
    "prompt_en": "Implement a function that evaluates structured rules, returns deterministic decisions, and explains edge cases and test coverage.",
    "prompt_ru": "Реализуйте функцию, которая оценивает структурированные правила, возвращает детерминированное решение и объясняет edge cases и покрытие тестами.",
    "stack_focus_en": "General-purpose application logic and deterministic decision making",
    "stack_focus_ru": "General-purpose application logic и детерминированное принятие решений",
    "preferred_language": "python",
    "workspace_hint_en": "A free-form solution is acceptable. Show the key decision branches, validation, and how you would test the behavior.",
    "workspace_hint_ru": "Подойдёт свободное решение. Покажите ключевые decision branches, валидацию и то, как вы бы тестировали поведение.",
}
_SQL_LIVE_SCENARIOS: dict[str, dict[str, str]] = {
    "backend_engineer": {
        "scenario_id": "customer_revenue_rollup",
        "title_en": "customer revenue rollup",
        "title_ru": "агрегация выручки по клиентам",
        "prompt_en": "Write a SQL query over customers and orders that returns the columns customer_name, completed_order_count, and completed_revenue for each active customer in March 2024. Include only customers with revenue >= 100 and order the result by completed_revenue descending, then customer_name ascending.",
        "prompt_ru": "Напишите SQL-запрос по таблицам customers и orders, который вернёт колонки customer_name, completed_order_count и completed_revenue для каждого активного клиента за март 2024 года. Оставьте только клиентов с выручкой >= 100 и отсортируйте результат по completed_revenue по убыванию, затем по customer_name по возрастанию.",
        "stack_focus_en": "SQL joins, filtered aggregations, and deterministic reporting output",
        "stack_focus_ru": "SQL joins, filtered aggregations и детерминированный reporting output",
        "preferred_language": "sql",
        "workspace_hint_en": "Focus on join logic, filters, aggregate correctness, and predictable ordering.",
        "workspace_hint_ru": "Сфокусируйтесь на логике join, фильтрах, корректности агрегаций и предсказуемой сортировке.",
    },
    "data_scientist": {
        "scenario_id": "signup_funnel_rollup",
        "title_en": "signup funnel breakdown",
        "title_ru": "разбор signup funnel",
        "prompt_en": "Write a SQL query over daily signup events that returns event_date, started_users, verified_users, and verified_rate for each day in the target week. Include only days with at least 3 signup starts and order by event_date ascending.",
        "prompt_ru": "Напишите SQL-запрос по daily signup events, который вернёт event_date, started_users, verified_users и verified_rate для каждого дня целевой недели. Оставьте только дни минимум с 3 signup starts и отсортируйте по event_date по возрастанию.",
        "stack_focus_en": "Analytical SQL, grouped funnel metrics, and numeric precision",
        "stack_focus_ru": "Аналитический SQL, grouped funnel metrics и численная точность",
        "preferred_language": "sql",
        "workspace_hint_en": "Focus on daily grouping, conditional aggregation, and a stable conversion-rate calculation.",
        "workspace_hint_ru": "Сфокусируйтесь на дневной группировке, условных агрегациях и стабильном расчёте conversion rate.",
    },
}
_SQL_LIVE_EXTRA_SCENARIOS: dict[str, dict[str, str]] = {
    "incident_error_budget_audit": {
        "scenario_id": "incident_error_budget_audit",
        "title_en": "error budget audit",
        "title_ru": "аудит error budget",
        "prompt_en": "Write a SQL query over daily service metrics that returns service_name, breach_days, and max_error_rate for services that exceeded the 1% error budget on at least 2 days in April 2024. Order by breach_days descending, then service_name ascending.",
        "prompt_ru": "Напишите SQL-запрос по ежедневным сервисным метрикам, который вернёт service_name, breach_days и max_error_rate для сервисов, превысивших error budget в 1% минимум в 2 дня апреля 2024 года. Сортировка: сначала breach_days по убыванию, затем service_name по возрастанию.",
        "stack_focus_en": "Operational SQL, threshold filters, and service-level aggregation",
        "stack_focus_ru": "Operational SQL, пороговые фильтры и сервисные агрегации",
        "preferred_language": "sql",
        "workspace_hint_en": "Focus on date filtering, threshold logic, and grouping that stays readable for ops reporting.",
        "workspace_hint_ru": "Сфокусируйтесь на фильтрации по датам, пороговой логике и группировке, пригодной для ops reporting.",
    },
}
_SQL_LIVE_DEFAULT_SCENARIO = {
    "scenario_id": "customer_revenue_rollup",
    "title_en": "customer revenue rollup",
    "title_ru": "агрегация выручки по клиентам",
    "prompt_en": "Write a SQL query over customers and orders that returns the columns customer_name, completed_order_count, and completed_revenue for each active customer in March 2024. Include only customers with revenue >= 100 and order the result by completed_revenue descending, then customer_name ascending.",
    "prompt_ru": "Напишите SQL-запрос по таблицам customers и orders, который вернёт колонки customer_name, completed_order_count и completed_revenue для каждого активного клиента за март 2024 года. Оставьте только клиентов с выручкой >= 100 и отсортируйте результат по completed_revenue по убыванию, затем по customer_name по возрастанию.",
    "stack_focus_en": "SQL joins, filtered aggregations, and deterministic reporting output",
    "stack_focus_ru": "SQL joins, filtered aggregations и детерминированный reporting output",
    "preferred_language": "sql",
    "workspace_hint_en": "Focus on join logic, filters, aggregate correctness, and predictable ordering.",
    "workspace_hint_ru": "Сфокусируйтесь на логике join, фильтрах, корректности агрегаций и предсказуемой сортировке.",
}
_WRITTEN_COMMUNICATION_SCENARIOS: dict[str, dict[str, str]] = {
    "backend_engineer": {
        "scenario_id": "incident_stakeholder_update",
        "title_en": "an incident stakeholder update",
        "title_ru": "апдейт для стейкхолдеров по инциденту",
        "prompt_en": "Draft a concise written update for product and engineering leadership after a production incident caused delayed notifications for enterprise customers. Explain impact, current status, immediate mitigation, and the next update cadence without overpromising.",
        "prompt_ru": "Подготовьте краткий письменный апдейт для product и engineering leadership после production-инцидента, из-за которого enterprise-клиенты получали уведомления с задержкой. Объясните impact, текущий статус, немедленные меры и ритм следующих апдейтов без лишних обещаний.",
        "workspace_hint_en": "Use the workspace to draft the actual message. Aim for a calm tone, clear ownership, and explicit next steps for a mixed technical and business audience.",
        "workspace_hint_ru": "Используйте workspace для самого текста сообщения. Держите спокойный тон, явный ownership и понятные следующие шаги для смешанной технической и бизнес-аудитории.",
    },
    "frontend_engineer": {
        "scenario_id": "design_system_migration_note",
        "title_en": "a design system migration note",
        "title_ru": "записка о миграции на design system",
        "prompt_en": "Write a rollout note for frontend engineers and product designers about moving a key surface to a new design system component set. Clarify what changes now, migration risks, and how teams should adopt the update safely.",
        "prompt_ru": "Напишите rollout-note для frontend-инженеров и product-дизайнеров о переводе ключевого продукта на новый набор design system компонентов. Объясните, что меняется сейчас, какие есть migration risks и как командам безопасно внедрять обновление.",
        "workspace_hint_en": "Structure the note so busy product teams can scan it quickly: what changed, what to do, and where the risk sits.",
        "workspace_hint_ru": "Постройте записку так, чтобы занятые продуктовые команды быстро считали: что изменилось, что делать и где лежит риск.",
    },
    "qa_engineer": {
        "scenario_id": "release_risk_recommendation",
        "title_en": "a release-risk recommendation",
        "title_ru": "рекомендация по релизному риску",
        "prompt_en": "Draft a written recommendation for an engineering manager about whether to ship a release that still has one intermittent checkout bug and two lower-severity UI issues. Explain the risk, trade-offs, and your recommended release decision.",
        "prompt_ru": "Подготовьте письменную рекомендацию для engineering manager о том, стоит ли выпускать релиз, в котором остался один плавающий баг в checkout и две UI-проблемы меньшей критичности. Объясните риск, trade-offs и рекомендованное решение по релизу.",
        "workspace_hint_en": "Make the recommendation actionable: state the decision, why it is justified, and what mitigation or follow-up is required.",
        "workspace_hint_ru": "Сделайте рекомендацию actionable: зафиксируйте решение, почему оно оправдано и какие mitigation или follow-up нужны дальше.",
    },
    "devops_engineer": {
        "scenario_id": "change_freeze_request",
        "title_en": "a change-freeze request",
        "title_ru": "запрос на change freeze",
        "prompt_en": "Write a short proposal to leadership requesting a temporary change freeze after repeated deployment instability across two regions. Explain the operational risk, what the freeze enables, and how you will decide when to lift it.",
        "prompt_ru": "Напишите короткое предложение для leadership с запросом на временный change freeze после повторяющейся нестабильности деплоев в двух регионах. Объясните операционный риск, что даст freeze и по каким сигналам вы будете его снимать.",
        "workspace_hint_en": "Keep the tone operational and credible. Leadership should understand both the urgency and the exit criteria.",
        "workspace_hint_ru": "Сохраните операционный и убедительный тон. Leadership должно понять и срочность, и критерии выхода из freeze.",
    },
    "data_scientist": {
        "scenario_id": "experiment_readout_note",
        "title_en": "an experiment readout note",
        "title_ru": "записка по итогам эксперимента",
        "prompt_en": "Draft a short readout for product leadership summarizing an experiment that improved activation but reduced short-term monetization. Explain the result, uncertainty, and what decision you recommend next.",
        "prompt_ru": "Подготовьте короткий readout для product leadership по эксперименту, который улучшил activation, но снизил краткосрочную монетизацию. Объясните результат, неопределённость и какое следующее решение вы рекомендуете.",
        "workspace_hint_en": "Balance evidence and uncertainty. The message should help leaders make a decision, not just restate the metrics.",
        "workspace_hint_ru": "Сбалансируйте evidence и неопределённость. Сообщение должно помогать лидерам принять решение, а не просто повторять метрики.",
    },
    "product_manager": {
        "scenario_id": "stakeholder_alignment_brief",
        "title_en": "a stakeholder alignment brief",
        "title_ru": "brief для выравнивания стейкхолдеров",
        "prompt_en": "Write a stakeholder brief explaining why a planned roadmap item should be delayed by one sprint because discovery uncovered a bigger integration dependency. Clarify impact, options, and the decision you want from leadership.",
        "prompt_ru": "Напишите stakeholder brief о том, почему запланированный roadmap item нужно сдвинуть на один спринт, потому что discovery выявил более крупную интеграционную зависимость. Проясните impact, варианты и какое решение вы ждёте от leadership.",
        "workspace_hint_en": "Optimize for alignment: make the trade-off explicit, keep the ask concrete, and avoid vague product language.",
        "workspace_hint_ru": "Оптимизируйте текст под выравнивание: явно покажите trade-off, сформулируйте конкретный запрос и избегайте расплывчатого продуктового языка.",
    },
    "mobile_engineer": {
        "scenario_id": "mobile_release_hotfix_note",
        "title_en": "a mobile hotfix note",
        "title_ru": "записка по mobile hotfix",
        "prompt_en": "Draft a note for support and product teams explaining a mobile hotfix for a crash affecting a subset of Android users. Describe impact, workaround status, and what teams should communicate externally until the fix is fully rolled out.",
        "prompt_ru": "Подготовьте записку для support и product команд о mobile hotfix для крэша, затрагивающего часть Android-пользователей. Опишите impact, статус workaround и что командам нужно коммуницировать наружу, пока фикс полностью не раскатан.",
        "workspace_hint_en": "Write for cross-functional readers who need a usable message quickly. Keep status, impact, and external communication guidance easy to scan.",
        "workspace_hint_ru": "Пишите для кросс-функциональной аудитории, которой нужен быстро применимый текст. Статус, impact и рекомендации для внешней коммуникации должны легко сканироваться.",
    },
    "designer": {
        "scenario_id": "design_rationale_note",
        "title_en": "a design rationale note",
        "title_ru": "design rationale note",
        "prompt_en": "Write a short rationale note explaining a controversial UX change that reduces customization in order to improve usability and support burden. Clarify who benefits, what trade-off was made, and how you would address likely objections.",
        "prompt_ru": "Напишите короткую rationale note, объясняющую спорное UX-изменение, которое уменьшает кастомизацию ради лучшей usability и снижения нагрузки на поддержку. Объясните, кто выигрывает, какой trade-off был принят и как вы ответите на ожидаемые возражения.",
        "workspace_hint_en": "Aim for a persuasive but measured tone. The note should show empathy for objections while still defending the decision clearly.",
        "workspace_hint_ru": "Держите убедительный, но сдержанный тон. Записка должна показывать эмпатию к возражениям и при этом ясно защищать решение.",
    },
}
_WRITTEN_COMMUNICATION_DEFAULT_SCENARIO = {
    "scenario_id": "cross_functional_status_note",
    "title_en": "a cross-functional status note",
    "title_ru": "кросс-функциональный статус-апдейт",
    "prompt_en": "Draft a concise update for mixed business and technical stakeholders about a delayed initiative. Explain status, impact, next steps, and the one key decision or expectation you need from the audience.",
    "prompt_ru": "Подготовьте краткий апдейт для смешанной бизнес- и технической аудитории по задержавшейся инициативе. Объясните статус, impact, следующие шаги и одно ключевое решение или ожидание, которое вам нужно от аудитории.",
    "workspace_hint_en": "Keep the structure explicit: context, impact, next steps, and ask. The writing should be easy to skim and hard to misinterpret.",
    "workspace_hint_ru": "Сделайте структуру явной: контекст, impact, следующие шаги и запрос. Текст должен легко сканироваться и не допускать двусмысленности.",
}


def _build_scenario_catalog(*sources: dict[str, dict[str, str]], default_scenario: dict[str, str]) -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for source in sources:
        for scenario in source.values():
            scenario_id = str(scenario.get("scenario_id") or "").strip()
            if scenario_id:
                catalog[scenario_id] = dict(scenario)
    default_id = str(default_scenario.get("scenario_id") or "").strip()
    if default_id:
        catalog[default_id] = dict(default_scenario)
    return catalog


_SYSTEM_DESIGN_SCENARIO_CATALOG = _build_scenario_catalog(
    _SYSTEM_DESIGN_SCENARIOS,
    default_scenario=_SYSTEM_DESIGN_DEFAULT_SCENARIO,
)
_BEHAVIORAL_INTERVIEW_SCENARIO_CATALOG = _build_scenario_catalog(
    _BEHAVIORAL_INTERVIEW_SCENARIOS,
    default_scenario=_BEHAVIORAL_INTERVIEW_DEFAULT_SCENARIO,
)
_CODING_TASK_SCENARIO_CATALOG = _build_scenario_catalog(
    _CODING_TASK_SCENARIOS,
    default_scenario=_CODING_TASK_DEFAULT_SCENARIO,
)
_SQL_LIVE_SCENARIO_CATALOG = _build_scenario_catalog(
    _SQL_LIVE_SCENARIOS,
    _SQL_LIVE_EXTRA_SCENARIOS,
    default_scenario=_SQL_LIVE_DEFAULT_SCENARIO,
)
_WRITTEN_COMMUNICATION_SCENARIO_CATALOG = _build_scenario_catalog(
    _WRITTEN_COMMUNICATION_SCENARIOS,
    default_scenario=_WRITTEN_COMMUNICATION_DEFAULT_SCENARIO,
)


def _resolve_scenario_definition(
    *,
    target_role: str,
    requested_id: str | None,
    role_scenarios: dict[str, dict[str, str]],
    default_scenario: dict[str, str],
    catalog: dict[str, dict[str, str]],
) -> dict[str, str]:
    normalized_requested_id = str(requested_id or "").strip()
    if normalized_requested_id and normalized_requested_id in catalog:
        return dict(catalog[normalized_requested_id])
    return dict(role_scenarios.get(target_role, default_scenario))


def _module_title_fallback(module_type: str) -> str:
    return module_type.replace("_", " ").strip().title() or "Assessment Module"


def _is_staged_module_type(module_type: str | None) -> bool:
    return module_type in {
        _SYSTEM_DESIGN_MODULE_TYPE,
        _BEHAVIORAL_INTERVIEW_MODULE_TYPE,
        _CODING_TASK_MODULE_TYPE,
        _SQL_LIVE_MODULE_TYPE,
        _WRITTEN_COMMUNICATION_MODULE_TYPE,
    }


def _is_workspace_artifact_module_type(module_type: str | None) -> bool:
    return module_type in {_CODING_TASK_MODULE_TYPE, _SQL_LIVE_MODULE_TYPE}


def _is_written_artifact_module_type(module_type: str | None) -> bool:
    return module_type == _WRITTEN_COMMUNICATION_MODULE_TYPE


def _select_system_design_scenario(
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str]:
    config = module_config if isinstance(module_config, dict) else {}
    scenario = _resolve_scenario_definition(
        target_role=target_role,
        requested_id=str(config.get("scenario_id") or "").strip() or None,
        role_scenarios=_SYSTEM_DESIGN_SCENARIOS,
        default_scenario=_SYSTEM_DESIGN_DEFAULT_SCENARIO,
        catalog=_SYSTEM_DESIGN_SCENARIO_CATALOG,
    )
    title_override = str(config.get("scenario_title") or "").strip()
    prompt_override = str(config.get("scenario_prompt") or "").strip()
    is_en = language == "en"
    return {
        "scenario_id": scenario["scenario_id"],
        "title": title_override or (scenario["title_en"] if is_en else scenario["title_ru"]),
        "prompt": prompt_override or (scenario["prompt_en"] if is_en else scenario["prompt_ru"]),
    }


def _select_behavioral_interview_scenario(
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str]:
    config = module_config if isinstance(module_config, dict) else {}
    scenario = _resolve_scenario_definition(
        target_role=target_role,
        requested_id=str(config.get("scenario_id") or "").strip() or None,
        role_scenarios=_BEHAVIORAL_INTERVIEW_SCENARIOS,
        default_scenario=_BEHAVIORAL_INTERVIEW_DEFAULT_SCENARIO,
        catalog=_BEHAVIORAL_INTERVIEW_SCENARIO_CATALOG,
    )
    title_override = str(config.get("scenario_title") or "").strip()
    prompt_override = str(config.get("scenario_prompt") or "").strip()
    is_en = language == "en"
    return {
        "scenario_id": scenario["scenario_id"],
        "title": title_override or (scenario["title_en"] if is_en else scenario["title_ru"]),
        "prompt": prompt_override or (scenario["prompt_en"] if is_en else scenario["prompt_ru"]),
    }


def _select_coding_task_scenario(
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str]:
    config = module_config if isinstance(module_config, dict) else {}
    scenario = _resolve_scenario_definition(
        target_role=target_role,
        requested_id=str(config.get("scenario_id") or "").strip() or None,
        role_scenarios=_CODING_TASK_SCENARIOS,
        default_scenario=_CODING_TASK_DEFAULT_SCENARIO,
        catalog=_CODING_TASK_SCENARIO_CATALOG,
    )
    title_override = str(config.get("scenario_title") or "").strip()
    prompt_override = str(config.get("scenario_prompt") or "").strip()
    is_en = language == "en"
    return {
        "scenario_id": scenario["scenario_id"],
        "title": title_override or (scenario["title_en"] if is_en else scenario["title_ru"]),
        "prompt": prompt_override or (scenario["prompt_en"] if is_en else scenario["prompt_ru"]),
        "stack_focus": str(scenario["stack_focus_en"] if is_en else scenario["stack_focus_ru"]).strip() or None,
        "preferred_language": str(scenario.get("preferred_language") or "").strip() or None,
        "workspace_hint": str(scenario["workspace_hint_en"] if is_en else scenario["workspace_hint_ru"]).strip() or None,
    }


def _select_sql_live_scenario(
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str]:
    config = module_config if isinstance(module_config, dict) else {}
    scenario = _resolve_scenario_definition(
        target_role=target_role,
        requested_id=str(config.get("scenario_id") or "").strip() or None,
        role_scenarios=_SQL_LIVE_SCENARIOS,
        default_scenario=_SQL_LIVE_DEFAULT_SCENARIO,
        catalog=_SQL_LIVE_SCENARIO_CATALOG,
    )
    title_override = str(config.get("scenario_title") or "").strip()
    prompt_override = str(config.get("scenario_prompt") or "").strip()
    is_en = language == "en"
    return {
        "scenario_id": scenario["scenario_id"],
        "title": title_override or (scenario["title_en"] if is_en else scenario["title_ru"]),
        "prompt": prompt_override or (scenario["prompt_en"] if is_en else scenario["prompt_ru"]),
        "stack_focus": str(scenario["stack_focus_en"] if is_en else scenario["stack_focus_ru"]).strip() or None,
        "preferred_language": str(scenario.get("preferred_language") or "").strip() or "sql",
        "workspace_hint": str(scenario["workspace_hint_en"] if is_en else scenario["workspace_hint_ru"]).strip() or None,
    }


def _select_written_communication_scenario(
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str]:
    config = module_config if isinstance(module_config, dict) else {}
    scenario = _resolve_scenario_definition(
        target_role=target_role,
        requested_id=str(config.get("scenario_id") or "").strip() or None,
        role_scenarios=_WRITTEN_COMMUNICATION_SCENARIOS,
        default_scenario=_WRITTEN_COMMUNICATION_DEFAULT_SCENARIO,
        catalog=_WRITTEN_COMMUNICATION_SCENARIO_CATALOG,
    )
    title_override = str(config.get("scenario_title") or "").strip()
    prompt_override = str(config.get("scenario_prompt") or "").strip()
    is_en = language == "en"
    return {
        "scenario_id": scenario["scenario_id"],
        "title": title_override or (scenario["title_en"] if is_en else scenario["title_ru"]),
        "prompt": prompt_override or (scenario["prompt_en"] if is_en else scenario["prompt_ru"]),
        "workspace_hint": str(scenario["workspace_hint_en"] if is_en else scenario["workspace_hint_ru"]).strip() or None,
    }


def build_assessment_module_preview(
    *,
    module_type: str | None,
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str | None] | None:
    normalized_module_type = str(module_type or "").strip().lower()
    if normalized_module_type == _SYSTEM_DESIGN_MODULE_TYPE:
        scenario = _select_system_design_scenario(target_role, language, module_config)
        return {
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
            "stack_focus": None,
            "preferred_language": None,
            "workspace_hint": None,
        }
    if normalized_module_type == _BEHAVIORAL_INTERVIEW_MODULE_TYPE:
        scenario = _select_behavioral_interview_scenario(target_role, language, module_config)
        return {
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
            "stack_focus": None,
            "preferred_language": None,
            "workspace_hint": None,
        }
    if normalized_module_type == _CODING_TASK_MODULE_TYPE:
        scenario = _select_coding_task_scenario(target_role, language, module_config)
        return {
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
            "stack_focus": scenario.get("stack_focus"),
            "preferred_language": scenario.get("preferred_language"),
            "workspace_hint": scenario.get("workspace_hint"),
        }
    if normalized_module_type == _SQL_LIVE_MODULE_TYPE:
        scenario = _select_sql_live_scenario(target_role, language, module_config)
        return {
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
            "stack_focus": scenario.get("stack_focus"),
            "preferred_language": scenario.get("preferred_language") or "sql",
            "workspace_hint": scenario.get("workspace_hint"),
        }
    if normalized_module_type == _WRITTEN_COMMUNICATION_MODULE_TYPE:
        scenario = _select_written_communication_scenario(target_role, language, module_config)
        return {
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
            "stack_focus": None,
            "preferred_language": None,
            "workspace_hint": scenario.get("workspace_hint"),
        }
    return None


def is_valid_assessment_module_scenario(
    *,
    module_type: str | None,
    scenario_id: str | None,
) -> bool:
    normalized_module_type = str(module_type or "").strip().lower()
    normalized_scenario_id = str(scenario_id or "").strip()
    if not normalized_scenario_id:
        return True
    if normalized_module_type == _SYSTEM_DESIGN_MODULE_TYPE:
        return normalized_scenario_id in _SYSTEM_DESIGN_SCENARIO_CATALOG
    if normalized_module_type == _BEHAVIORAL_INTERVIEW_MODULE_TYPE:
        return normalized_scenario_id in _BEHAVIORAL_INTERVIEW_SCENARIO_CATALOG
    if normalized_module_type == _CODING_TASK_MODULE_TYPE:
        return normalized_scenario_id in _CODING_TASK_SCENARIO_CATALOG
    if normalized_module_type == _SQL_LIVE_MODULE_TYPE:
        return normalized_scenario_id in _SQL_LIVE_SCENARIO_CATALOG
    if normalized_module_type == _WRITTEN_COMMUNICATION_MODULE_TYPE:
        return normalized_scenario_id in _WRITTEN_COMMUNICATION_SCENARIO_CATALOG
    return True


def list_assessment_module_profile_options(
    *,
    target_role: str,
    language: str,
) -> dict[str, list[dict[str, Any]]]:
    is_en = language == "en"

    def _ordered_options(
        *,
        role_scenarios: dict[str, dict[str, str]],
        default_scenario: dict[str, str],
        catalog: dict[str, dict[str, str]],
        module_type: str,
    ) -> list[dict[str, Any]]:
        recommended_id = str(role_scenarios.get(target_role, default_scenario).get("scenario_id") or "").strip()
        options = [
            {
                "scenario_id": scenario_id,
                "title": str(item["title_en"] if is_en else item["title_ru"]).strip(),
                "prompt": str(item["prompt_en"] if is_en else item["prompt_ru"]).strip(),
                "stack_focus": (
                    str(item["stack_focus_en"] if is_en else item["stack_focus_ru"]).strip()
                    if item.get("stack_focus_en") or item.get("stack_focus_ru")
                    else None
                ),
                "preferred_language": str(item.get("preferred_language") or "").strip() or None,
                "workspace_hint": (
                    str(item["workspace_hint_en"] if is_en else item["workspace_hint_ru"]).strip()
                    if item.get("workspace_hint_en") or item.get("workspace_hint_ru")
                    else None
                ),
                "recommended": scenario_id == recommended_id,
                "module_type": module_type,
            }
            for scenario_id, item in catalog.items()
        ]
        return sorted(options, key=lambda item: (not bool(item["recommended"]), str(item["title"]).lower()))

    return {
        "coding_task": _ordered_options(
            role_scenarios=_CODING_TASK_SCENARIOS,
            default_scenario=_CODING_TASK_DEFAULT_SCENARIO,
            catalog=_CODING_TASK_SCENARIO_CATALOG,
            module_type=_CODING_TASK_MODULE_TYPE,
        ),
        "sql_live": _ordered_options(
            role_scenarios=_SQL_LIVE_SCENARIOS,
            default_scenario=_SQL_LIVE_DEFAULT_SCENARIO,
            catalog=_SQL_LIVE_SCENARIO_CATALOG,
            module_type=_SQL_LIVE_MODULE_TYPE,
        ),
    }


def _build_system_design_topic_plan(
    *,
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenario = _select_system_design_scenario(target_role, language, module_config)
    is_en = language == "en"
    stage_titles = {
        "requirements": "Requirements & Constraints" if is_en else "Требования и ограничения",
        "high_level_design": "High-Level Design" if is_en else "High-level дизайн",
        "tradeoffs": "Trade-Offs & Failure Modes" if is_en else "Trade-offs и failure modes",
    }
    stage_prompts = {
        "requirements": (
            "Clarify users, traffic, SLAs, consistency needs, integrations, and non-functional constraints before committing to architecture."
            if is_en
            else "Уточните пользователей, объёмы трафика, SLA, требования к консистентности, интеграции и нефункциональные ограничения до выбора архитектуры."
        ),
        "high_level_design": (
            "Describe the end-to-end architecture: clients, APIs, core services, async processing, data stores, scaling, and observability."
            if is_en
            else "Опишите end-to-end архитектуру: клиенты, API, основные сервисы, async processing, хранилища, масштабирование и observability."
        ),
        "tradeoffs": (
            "Explain the main trade-offs, bottlenecks, reliability choices, cost decisions, and what changes first at 10x scale."
            if is_en
            else "Объясните ключевые trade-offs, узкие места, выборы по надёжности и стоимости, а также что меняется первым при росте нагрузки в 10 раз."
        ),
    }
    competencies_by_stage = {
        "requirements": ["System Design & Architecture", "Technical Communication"],
        "high_level_design": ["System Design & Architecture", "Database Design & Optimization", "API Design & Protocols"],
        "tradeoffs": ["System Design & Architecture", "Debugging & Problem Decomposition", "Ownership & Growth Mindset"],
    }
    stage_plan = [
        {
            "stage_key": stage_key,
            "stage_title": stage_titles[stage_key],
            "stage_prompt": stage_prompts[stage_key],
        }
        for stage_key in _SYSTEM_DESIGN_STAGE_KEYS
    ]
    topic_plan = [
        {
            "competencies": competencies_by_stage[item["stage_key"]],
            "resume_anchor": None,
            "verification_target": None,
            "stage_key": item["stage_key"],
            "stage_title": item["stage_title"],
            "stage_prompt": item["stage_prompt"],
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
        }
        for item in stage_plan
    ]
    module_context = {
        "module_type": _SYSTEM_DESIGN_MODULE_TYPE,
        "scenario_id": scenario["scenario_id"],
        "scenario_title": scenario["title"],
        "scenario_prompt": scenario["prompt"],
        "stage_plan": stage_plan,
        "question_history": [
            {
                "assistant_turn": 1,
                "stage_key": stage_plan[0]["stage_key"],
                "stage_title": stage_plan[0]["stage_title"],
            }
        ],
    }
    return topic_plan, module_context


def _build_behavioral_interview_topic_plan(
    *,
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenario = _select_behavioral_interview_scenario(target_role, language, module_config)
    is_en = language == "en"
    stage_titles = {
        "ownership": "Ownership Under Ambiguity" if is_en else "Ownership в неоднозначности",
        "collaboration": "Cross-Functional Collaboration" if is_en else "Кросс-функциональное взаимодействие",
        "leadership": "Influence Under Pressure" if is_en else "Влияние под давлением",
        "reflection": "Reflection & Growth" if is_en else "Рефлексия и рост",
    }
    stage_prompts = {
        "ownership": (
            "Ask for a concrete situation where scope, expectations, or constraints were unclear and the candidate still had to take responsibility and decide what to do next."
            if is_en
            else "Спросите о конкретной ситуации, где scope, ожидания или ограничения были неясны, но кандидату всё равно пришлось взять ответственность и решить, что делать дальше."
        ),
        "collaboration": (
            "Ask for a concrete example of disagreement, tension, or dependency with another team or stakeholder and how the candidate handled alignment."
            if is_en
            else "Спросите о конкретном примере несогласия, напряжения или зависимости с другой командой или стейкхолдером и о том, как кандидат выстраивал выравнивание."
        ),
        "leadership": (
            "Ask for a concrete situation where the candidate had to influence others, create clarity, or lead a response under time pressure without relying only on formal authority."
            if is_en
            else "Спросите о конкретной ситуации, где кандидату пришлось влиять на других, наводить ясность или вести реакцию под давлением времени, не опираясь только на формальную власть."
        ),
        "reflection": (
            "Ask for a concrete mistake, piece of tough feedback, or failed judgment call and what changed in the candidate's behavior afterward."
            if is_en
            else "Спросите о конкретной ошибке, жёсткой обратной связи или неудачном решении и о том, что изменилось в поведении кандидата после этого."
        ),
    }
    competencies_by_stage = {
        "ownership": ["Ownership & Growth Mindset", "Technical Communication"],
        "collaboration": ["Collaboration & Cross-functional Work", "Stakeholder Communication"],
        "leadership": ["Leadership & Influence", "Technical Communication"],
        "reflection": ["Ownership & Growth Mindset", "Analytical Problem Solving"],
    }
    stage_plan = [
        {
            "stage_key": stage_key,
            "stage_title": stage_titles[stage_key],
            "stage_prompt": stage_prompts[stage_key],
        }
        for stage_key in _BEHAVIORAL_INTERVIEW_STAGE_KEYS
    ]
    topic_plan = [
        {
            "competencies": competencies_by_stage[item["stage_key"]],
            "resume_anchor": None,
            "verification_target": None,
            "stage_key": item["stage_key"],
            "stage_title": item["stage_title"],
            "stage_prompt": item["stage_prompt"],
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
        }
        for item in stage_plan
    ]
    module_context = {
        "module_type": _BEHAVIORAL_INTERVIEW_MODULE_TYPE,
        "scenario_id": scenario["scenario_id"],
        "scenario_title": scenario["title"],
        "scenario_prompt": scenario["prompt"],
        "stage_plan": stage_plan,
        "question_history": [
            {
                "assistant_turn": 1,
                "stage_key": stage_plan[0]["stage_key"],
                "stage_title": stage_plan[0]["stage_title"],
            }
        ],
    }
    return topic_plan, module_context


def _build_coding_task_topic_plan(
    *,
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenario = _select_coding_task_scenario(target_role, language, module_config)
    is_en = language == "en"
    stage_titles = {
        "task_brief": "Task Breakdown" if is_en else "Декомпозиция задачи",
        "implementation": "Implementation" if is_en else "Реализация",
        "review": "Testing & Review" if is_en else "Проверка и review",
    }
    stage_prompts = {
        "task_brief": (
            "Clarify inputs, outputs, constraints, edge cases, and the implementation strategy before writing code."
            if is_en
            else "Уточните входы, выходы, ограничения, edge cases и стратегию реализации до написания кода."
        ),
        "implementation": (
            "Share the core implementation or concise pseudocode, and explain the important functions or state transitions."
            if is_en
            else "Покажите core implementation или компактный псевдокод и объясните ключевые функции или переходы состояния."
        ),
        "review": (
            "Explain time/space complexity, testing strategy, failure cases, and what you would refactor next."
            if is_en
            else "Объясните time/space complexity, стратегию тестирования, failure cases и что вы бы рефакторили следующим."
        ),
    }
    competencies_by_stage = {
        "task_brief": ["Problem Solving", "Debugging & Problem Decomposition"],
        "implementation": ["Code Quality & Maintainability", "Technical Communication"],
        "review": ["Testing Strategy", "Ownership & Growth Mindset"],
    }
    stage_plan = [
        {
            "stage_key": stage_key,
            "stage_title": stage_titles[stage_key],
            "stage_prompt": stage_prompts[stage_key],
        }
        for stage_key in _CODING_TASK_STAGE_KEYS
    ]
    topic_plan = [
        {
            "competencies": competencies_by_stage[item["stage_key"]],
            "resume_anchor": None,
            "verification_target": None,
            "stage_key": item["stage_key"],
            "stage_title": item["stage_title"],
            "stage_prompt": item["stage_prompt"],
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
        }
        for item in stage_plan
    ]
    module_context = {
        "module_type": _CODING_TASK_MODULE_TYPE,
        "scenario_id": scenario["scenario_id"],
        "scenario_title": scenario["title"],
        "scenario_prompt": scenario["prompt"],
        "stack_focus": scenario.get("stack_focus"),
        "preferred_language": scenario.get("preferred_language"),
        "workspace_hint": scenario.get("workspace_hint"),
        "stage_plan": stage_plan,
        "question_history": [
            {
                "assistant_turn": 1,
                "stage_key": stage_plan[0]["stage_key"],
                "stage_title": stage_plan[0]["stage_title"],
            }
        ],
    }
    return topic_plan, module_context


def _build_sql_live_topic_plan(
    *,
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenario = _select_sql_live_scenario(target_role, language, module_config)
    is_en = language == "en"
    stage_titles = {
        "schema_review": "Schema & Query Plan" if is_en else "Схема и план запроса",
        "query_authoring": "Query Authoring" if is_en else "Написание запроса",
        "result_review": "Validation & Optimization" if is_en else "Проверка и оптимизация",
    }
    stage_prompts = {
        "schema_review": (
            "Clarify the relevant tables, join keys, filters, aggregation rules, and the shape of the final result before writing SQL."
            if is_en
            else "Уточните нужные таблицы, ключи join, фильтры, правила агрегации и форму итогового результата до написания SQL."
        ),
        "query_authoring": (
            "Write the SQL query itself and explain the most important join, grouping, filtering, and ordering decisions."
            if is_en
            else "Напишите сам SQL-запрос и объясните ключевые решения по join, grouping, filtering и ordering."
        ),
        "result_review": (
            "Explain how you would validate correctness, handle tricky rows, and improve readability or performance if the dataset grows."
            if is_en
            else "Объясните, как вы бы проверяли корректность, обрабатывали tricky rows и улучшали читаемость или производительность при росте данных."
        ),
    }
    competencies_by_stage = {
        "schema_review": ["Database Design & Optimization", "Problem Solving"],
        "query_authoring": ["Database Design & Optimization", "Technical Communication"],
        "result_review": ["Debugging & Problem Decomposition", "Ownership & Growth Mindset"],
    }
    stage_plan = [
        {
            "stage_key": stage_key,
            "stage_title": stage_titles[stage_key],
            "stage_prompt": stage_prompts[stage_key],
        }
        for stage_key in _SQL_LIVE_STAGE_KEYS
    ]
    topic_plan = [
        {
            "competencies": competencies_by_stage[item["stage_key"]],
            "resume_anchor": None,
            "verification_target": None,
            "stage_key": item["stage_key"],
            "stage_title": item["stage_title"],
            "stage_prompt": item["stage_prompt"],
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
        }
        for item in stage_plan
    ]
    module_context = {
        "module_type": _SQL_LIVE_MODULE_TYPE,
        "scenario_id": scenario["scenario_id"],
        "scenario_title": scenario["title"],
        "scenario_prompt": scenario["prompt"],
        "stack_focus": scenario.get("stack_focus"),
        "preferred_language": scenario.get("preferred_language") or "sql",
        "workspace_hint": scenario.get("workspace_hint"),
        "stage_plan": stage_plan,
        "question_history": [
            {
                "assistant_turn": 1,
                "stage_key": stage_plan[0]["stage_key"],
                "stage_title": stage_plan[0]["stage_title"],
            }
        ],
    }
    return topic_plan, module_context


def _build_written_communication_topic_plan(
    *,
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenario = _select_written_communication_scenario(target_role, language, module_config)
    is_en = language == "en"
    stage_titles = {
        "brief_alignment": "Audience & Goal" if is_en else "Аудитория и цель",
        "drafting": "Drafting" if is_en else "Подготовка черновика",
        "editing": "Revision & Tone" if is_en else "Редактура и тон",
    }
    stage_prompts = {
        "brief_alignment": (
            "Clarify the audience, the decision or alignment goal, the key facts to include, and what must stay explicit from the start."
            if is_en
            else "Уточните аудиторию, цель сообщения, ключевые факты, которые нужно включить, и что должно быть явно проговорено с самого начала."
        ),
        "drafting": (
            "Draft the core message in the workspace, keeping the structure crisp, the ownership clear, and the main ask easy to find."
            if is_en
            else "Соберите основной текст в workspace так, чтобы структура была чёткой, ownership понятным, а главный запрос легко находился."
        ),
        "editing": (
            "Revise for clarity, tone, and audience fit: remove ambiguity, tighten weak sections, and make the next steps explicit."
            if is_en
            else "Отредактируйте текст под ясность, тон и соответствие аудитории: уберите двусмысленность, усилите слабые места и явно зафиксируйте следующие шаги."
        ),
    }
    competencies_by_stage = {
        "brief_alignment": ["Technical Communication", "Problem Solving"],
        "drafting": ["Technical Communication", "Ownership & Growth Mindset"],
        "editing": ["Technical Communication", "Debugging & Problem Decomposition"],
    }
    stage_plan = [
        {
            "stage_key": stage_key,
            "stage_title": stage_titles[stage_key],
            "stage_prompt": stage_prompts[stage_key],
        }
        for stage_key in _WRITTEN_COMMUNICATION_STAGE_KEYS
    ]
    topic_plan = [
        {
            "competencies": competencies_by_stage[item["stage_key"]],
            "resume_anchor": None,
            "verification_target": None,
            "stage_key": item["stage_key"],
            "stage_title": item["stage_title"],
            "stage_prompt": item["stage_prompt"],
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_prompt": scenario["prompt"],
        }
        for item in stage_plan
    ]
    module_context = {
        "module_type": _WRITTEN_COMMUNICATION_MODULE_TYPE,
        "scenario_id": scenario["scenario_id"],
        "scenario_title": scenario["title"],
        "scenario_prompt": scenario["prompt"],
        "workspace_hint": scenario.get("workspace_hint"),
        "stage_plan": stage_plan,
        "question_history": [
            {
                "assistant_turn": 1,
                "stage_key": stage_plan[0]["stage_key"],
                "stage_title": stage_plan[0]["stage_title"],
            }
        ],
    }
    return topic_plan, module_context


def _build_interview_module_session_payload(interview: Interview) -> InterviewModuleSessionResponse | None:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    module_type = str(state.get("module_type") or "").strip().lower()
    if not module_type:
        return None

    stage_plan_raw = state.get("module_stage_plan")
    stage_plan = stage_plan_raw if isinstance(stage_plan_raw, list) else []
    stage_count = len(stage_plan)
    current_stage_index = min(max(_safe_int(state.get("module_stage_index"), 0), 0), max(stage_count - 1, 0))
    current_stage = stage_plan[current_stage_index] if stage_plan else {}

    return InterviewModuleSessionResponse(
        module_type=module_type,
        module_title=str(state.get("module_title") or _module_title_fallback(module_type)),
        scenario_id=str(state.get("module_scenario_id") or "") or None,
        scenario_title=str(state.get("module_scenario_title") or "") or None,
        scenario_prompt=str(state.get("module_scenario_prompt") or "") or None,
        stack_focus=str(state.get("module_stack_focus") or "") or None,
        preferred_language=str(state.get("module_preferred_language") or "") or None,
        workspace_hint=str(state.get("module_workspace_hint") or "") or None,
        stage_key=str(current_stage.get("stage_key") or state.get("module_stage_key") or "") or None,
        stage_title=str(current_stage.get("stage_title") or state.get("module_stage_title") or "") or None,
        stage_index=current_stage_index,
        stage_count=stage_count,
    )


_INTERVIEW_PHASE_TITLES = {
    "intro": {
        "en": "Self-introduction",
        "ru": "О себе и опыте",
    },
    "resume_followup": {
        "en": "Resume follow-up",
        "ru": "Разбор опыта из резюме",
    },
    "technical": {
        "en": "Technical validation",
        "ru": "Техническая валидация",
    },
    "behavioral_closing": {
        "en": "Behavioral closing",
        "ru": "Финальный behavioral-блок",
    },
}


def _phase_title(phase_key: str | None, language: str) -> str:
    normalized_phase = str(phase_key or "").strip().lower()
    normalized_language = "en" if str(language).strip().lower() == "en" else "ru"
    title = _INTERVIEW_PHASE_TITLES.get(normalized_phase, {}).get(normalized_language)
    if title:
        return title
    if not normalized_phase:
        return "Interview stage" if normalized_language == "en" else "Этап интервью"
    return normalized_phase.replace("_", " ").strip().title()


def _build_interview_stage_payload(interview: Interview) -> InterviewStageResponse | None:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    module_type = str(state.get("module_type") or "").strip().lower()
    if _is_staged_module_type(module_type):
        return None

    topic_plan_raw = state.get("topic_plan")
    topic_plan = topic_plan_raw if isinstance(topic_plan_raw, list) else []
    if not topic_plan:
        return None

    current_topic_index = min(
        max(_safe_int(state.get("current_topic_index"), max(interview.question_count - 1, 0)), 0),
        max(len(topic_plan) - 1, 0),
    )
    current_target = topic_plan[current_topic_index] if topic_plan else {}
    if not isinstance(current_target, dict):
        return None

    phase_key = str(current_target.get("phase") or "").strip().lower() or "technical"
    raw_competencies = current_target.get("competencies")
    competency_targets: list[str] = []
    if isinstance(raw_competencies, list):
        competency_targets = [str(item).strip() for item in raw_competencies if str(item).strip()]

    return InterviewStageResponse(
        phase_key=phase_key,
        phase_title=_phase_title(phase_key, interview.language),
        slot_number=current_topic_index + 1,
        slot_count=len(topic_plan),
        competency_targets=competency_targets,
        resume_anchor=str(current_target.get("resume_anchor") or "") or None,
        verification_target=str(current_target.get("verification_target") or "") or None,
    )


def _normalize_coding_task_language(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "python"
    return normalized[:40]


def _get_coding_task_artifact_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("coding_task_artifact")
    if not isinstance(raw, dict):
        return {}
    return raw


def _build_coding_task_artifact_response(interview: Interview) -> CodingTaskArtifactResponse:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    artifact = _get_coding_task_artifact_state(state)
    return CodingTaskArtifactResponse(
        interview_id=interview.id,
        language=_normalize_coding_task_language(artifact.get("language")),
        code=str(artifact.get("code") or ""),
        updated_at=_parse_iso_datetime(artifact.get("updated_at")),
    )


def _get_written_artifact_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("written_artifact")
    if not isinstance(raw, dict):
        return {}
    return raw


def _build_written_artifact_response(interview: Interview) -> WrittenArtifactResponse:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    artifact = _get_written_artifact_state(state)
    return WrittenArtifactResponse(
        interview_id=interview.id,
        content=str(artifact.get("content") or ""),
        updated_at=_parse_iso_datetime(artifact.get("updated_at")),
    )


def _ensure_coding_task_interview(interview: Interview) -> None:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    module_type = str(state.get("module_type") or "").strip().lower()
    if not _is_workspace_artifact_module_type(module_type):
        raise CodingTaskArtifactUnavailableError("Task workspace artifact is only available for coding_task or sql_live interviews.")


def _ensure_written_interview(interview: Interview) -> None:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    module_type = str(state.get("module_type") or "").strip().lower()
    if not _is_written_artifact_module_type(module_type):
        raise WrittenArtifactUnavailableError("Written artifact is only available for written_communication interviews.")


def _build_module_stage_map(interview: Interview) -> dict[int, dict[str, str]]:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    raw_history = state.get("module_question_history")
    if not isinstance(raw_history, list):
        return {}

    stage_map: dict[int, dict[str, str]] = {}
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        assistant_turn = _safe_int(item.get("assistant_turn"), 0)
        if assistant_turn <= 0:
            continue
        stage_map[assistant_turn] = {
            "stage_key": str(item.get("stage_key") or "") or None,
            "stage_title": str(item.get("stage_title") or "") or None,
        }
    return stage_map


def _to_history(messages: list[InterviewMessage]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _to_timestamps(messages: list[InterviewMessage]) -> list[dict]:
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in messages
    ]


def _get_competency_targets(
    interview: Interview,
    question_number: int,
) -> list[str] | None:
    """Get competency targets for the given question number from the stored plan."""
    plan = getattr(interview, '_competency_plan', None)
    if plan and 0 < question_number <= len(plan):
        return plan[question_number - 1]
    return None


def _save_skills(
    db: AsyncSession,
    candidate_id: uuid.UUID,
    report_id: uuid.UUID,
    skill_tags: list[dict],
) -> None:
    """Persist extracted skills to candidate_skills table."""
    for tag in skill_tags:
        skill_name = tag.get("skill", "").strip().lower()
        if not skill_name:
            continue
        db.add(CandidateSkill(
            id=uuid.uuid4(),
            candidate_id=candidate_id,
            report_id=report_id,
            skill_name=skill_name,
            proficiency=tag.get("proficiency", "intermediate"),
            evidence_summary=None,
        ))


_ANSWER_CLASS_PRIORITY = {
    "evasive": 0,
    "generic": 1,
    "no_experience_honest": 2,
    "partial": 3,
    "strong": 4,
}

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9_+#.-]+")
_QUESTION_STOPWORDS = {
    "как", "что", "где", "когда", "почему", "какие", "какой", "какую",
    "вы", "ты", "это", "этот", "эта", "именно", "your", "what", "how",
    "where", "when", "why", "which", "with", "from", "that", "this",
    "the", "and", "или", "для", "про", "was", "were", "there", "used",
}
_NONSENSE_MARKERS = (
    "asdf",
    "qwerty",
    "zxcv",
    "blah",
    "bla bla",
    "чушь",
    "абракадабра",
    "ываыва",
    "фыв",
)
_FILLER_NOISE_TOKENS = {
    "ээ",
    "эм",
    "ну",
    "типа",
    "короче",
    "блин",
    "вот",
    "yeah",
    "umm",
    "uh",
    "hmm",
}
_MAX_CHAT_QUESTION_WORDS = 36
_AMBIGUOUS_SHORT_QUESTION_RE = re.compile(
    r"^(как|где|когда|почему|зачем)\s+вы\s+(их|это|эти|такое|так|там|тут)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_SHORT_QUESTION_EN_RE = re.compile(
    r"^(how|where|when|why)\s+(did|do|would)\s+you\s+(that|those|it|them)\b",
    re.IGNORECASE,
)
_CLARIFICATION_REQUEST_RE = re.compile(
    r"(не\s*понял|непонятно|в\s+смысле|что(\s+именно)?\s+имеете\s+в\s+виду|уточните|поясните|повторите|кого\??$|чего\??$|what do you mean|not clear|didn'?t understand|can you clarify|could you clarify|sorry\??$)",
    re.IGNORECASE,
)
_MOVE_ON_REQUEST_RE = re.compile(
    r"(уже\s+ответ(ил|ила|ил[аи])|на\s+это\s+уже\s+ответ(ил|ила|ил[аи])|на\s+этот\s+вопрос\s+(я\s+)?уже\s+ответ(ил|ила|ил[аи])|это\s+уже\s+было|уже\s+(писал|писала|говорил|говорила)\s+выше|давайте\s+дальше|перейд(е|ё)м\s+дальше|перейти\s+дальше|следующ(ий|ая)\s+вопрос|i already answered|already answered|move on|next question|let'?s move on|already said above)",
    re.IGNORECASE,
)
_RUNTIME_EXAMPLE_MARKERS_RE = re.compile(
    r"(например|кейс|случа(й|я)|в\s+проекте|на\s+проекте|в\s+проде|for example|for instance|one time|in production|in prod|when i|we had)",
    re.IGNORECASE,
)
_RUNTIME_TECHNICAL_MARKERS_RE = re.compile(
    r"(\bapi\b|endpoint|sql|select\s+|join\b|index\b|query|postman|swagger|ci/cd|pipeline|git|rollback|kubernetes|k8s|docker|grafana|prometheus|slo|sla|latency|throughput|p95|p99|redis|kafka|pytest|unit test|integration test|regression|bug|дефект|лог|метрик|дашборд|нагрузк|стенд|релиз|миграц|валидац)",
    re.IGNORECASE,
)
_RUNTIME_INTERVIEWER_FAILURE_RE = re.compile(
    r"(не\s*понял|непонятно|что\s+имеете\s+в\s+виду|какая\s+задача|про\s+что\s+вопрос|didn'?t\s+understand|not\s+clear|what\s+do\s+you\s+mean)",
    re.IGNORECASE,
)
_RUNTIME_PERSONAL_ACTION_MARKERS_RE = re.compile(
    r"(\bя\b|\bмы\b|\bi\b|\bwe\b|"
    r"сделал[аи]?|сделал[аи]\s+лично|настроил[аи]?|реализовал[аи]?|внедрил[аи]?|"
    r"проверил[аи]?|написал[аи]?|добавил[аи]?|локализовал[аи]?|воспроизв[её]л[аи]?|"
    r"анализир(овал|ую|овали|уем)|тестир(овал|ую|овали|уем)|монитор(ил|ю|или|им)|"
    r"implemented|configured|designed|wrote|added|validated|reproduced|investigated|triaged)",
    re.IGNORECASE,
)
_RUNTIME_RESULT_MARKERS_RE = re.compile(
    r"(снизил[аи]?|повысил[аи]?|ускорил[аи]?|улучшил[аи]?|уменьшил[аи]?|"
    r"на\s+\d+%|на\s+\d+\s*(ms|сек|мин)|"
    r"принял[аи]?\s+на\s+сопровожд|не\s+повторял(ось|ся|ись)|стало\s+(лучше|быстрее|стабильнее)|"
    r"\b\d+\s+(систем|инцидент(ов)?|дефект(ов)?|заяв(ок|ки))\b|"
    r"p95|p99|sla|slo|"
    r"reduced|increased|improved|decreased|speedup|latency|throughput|error rate|passed|blocked release)",
    re.IGNORECASE,
)
_RUNTIME_TRADEOFF_MARKERS_RE = re.compile(
    r"(trade[\s-]?off|компромисс|выбирал[аи]?\s+между|между\s+.+\s+и\s+.+|"
    r"цена\s+решения|пожертвовал[аи]?|latency\s+vs\s+consistency|consistency\s+vs\s+availability)",
    re.IGNORECASE,
)
_RUNTIME_INTENT_CONFUSION_RE = re.compile(
    r"(^что\??$|не\s*понял|непонятно|какой\s+кейс|про\s+что|в\s+чем\s+вопрос|what\??$|i\s+don'?t\s+understand|not\s+clear)",
    re.IGNORECASE,
)
_RUNTIME_INTENT_META_RE = re.compile(
    r"(а\s+ты\s+сам\s+ответить\s+можешь|ты\s+сам\s+ответь|зачем\s+ты\s+спрашиваешь|why\s+are\s+you\s+asking|can\s+you\s+answer\s+yourself)",
    re.IGNORECASE,
)
_RUNTIME_INTENT_PERSONALIZE_RE = re.compile(
    r"(по\s+моему\s+опыту|по\s+моей\s+работе|давай\s+по\s+моему\s+опыту|давай\s+по\s+моей\s+работе|еще\s+вопросы\s+по\s+моей\s+работе|в\s+моем\s+контексте|based\s+on\s+my\s+experience)",
    re.IGNORECASE,
)
_RUNTIME_INTENT_REFUSAL_RE = re.compile(
    r"(^не\s+знаю$|^незнаю$|не\s+помню|затрудняюсь\s+ответить|без\s+понятия|don't\s+know|not\s+sure)",
    re.IGNORECASE,
)
_RUNTIME_GENERAL_WEAK_RE = re.compile(
    r"(^везде$|^логи$|^api$|^апи$|^проверю$|^посмотрю$|^статусы$|^не\s+знаю$|^незнаю$|everywhere|logs?$|api$|i'?ll\s+check)",
    re.IGNORECASE,
)


def _derive_adaptive_difficulty_tier(
    *,
    current_tier: int,
    answer_class: str,
    answer_relevance: str,
    strong_answers_count: int,
    weak_answers_count: int,
    consecutive_strong_answers: int = 0,
    consecutive_weak_answers: int = 0,
) -> int:
    tier = max(1, min(5, int(current_tier or 3)))
    if answer_class == "strong" and answer_relevance in {"medium", "high"}:
        tier += 1
    elif answer_class in {"generic", "evasive", "no_experience_honest"} or answer_relevance == "low":
        tier -= 1

    # Stabilize adaptation with streak signals so we don't oscillate too much
    # on single-turn noise.
    if consecutive_strong_answers >= 2:
        tier += 1
    elif consecutive_weak_answers >= 2:
        tier -= 1

    if strong_answers_count >= weak_answers_count + 3:
        tier += 1
    elif weak_answers_count >= strong_answers_count + 3:
        tier -= 1

    return max(1, min(5, tier))


def _proficiency_label_from_level(level: int, language: str) -> tuple[str, str]:
    # Unified 15-level ladder:
    # Junior 1..5 → Middle 1..5 → Senior 1..5
    normalized = max(1, min(15, int(level)))
    if normalized <= 5:
        rank = normalized
        key = f"junior_{rank}"
        label = f"Junior {rank}"
    elif normalized <= 10:
        rank = normalized - 5
        key = f"middle_{rank}"
        label = f"Middle {rank}"
    else:
        rank = normalized - 10
        key = f"senior_{rank}"
        label = f"Senior {rank}"

    # Labels are intentionally identical across locales to keep market-facing nomenclature stable.
    _ = language
    return key, label


def _safe_lower_set(values: list[Any] | tuple[Any, ...] | set[Any] | None) -> set[str]:
    return {
        str(item).strip().lower()
        for item in (values or [])
        if str(item).strip()
    }


def _confidence_verdict_for_value(confidence: float | None) -> str:
    value = max(0.0, min(1.0, float(confidence or 0.0)))
    if value < 0.40:
        return "insufficient_data"
    if value < 0.70:
        return "needs_human_review"
    return "normal"


def _compute_scoring_v2_evidence(
    *,
    target_role: str,
    competency_scores: list[dict] | None,
    competency_confidence: dict[str, float] | None,
    per_question_analysis: list[dict] | None,
    interview_meta: dict[str, Any] | None,
    evidence_coverage: dict[str, Any] | None,
) -> dict[str, Any]:
    competency_scores = list(competency_scores or [])
    competency_confidence = dict(competency_confidence or {})
    per_question_analysis = list(per_question_analysis or [])
    interview_meta = interview_meta or {}
    evidence_coverage = dict(evidence_coverage or {})

    role_competencies = [str(item).strip() for item in get_role_core_competency_order(target_role) if str(item).strip()]
    if not role_competencies:
        role_competencies = [str(item.get("competency") or "").strip() for item in competency_scores if str(item.get("competency") or "").strip()]
    role_competencies_lower = _safe_lower_set(role_competencies)

    answered_competencies: set[str] = set()
    answered_competencies_lower: set[str] = set()
    for item in per_question_analysis:
        for comp in item.get("targeted_competencies", []) or []:
            name = str(comp).strip()
            if not name:
                continue
            answered_competencies.add(name)
            answered_competencies_lower.add(name.lower())
    for topic in interview_meta.get("topic_plan", []) or []:
        for comp in topic.get("competencies", []) or []:
            name = str(comp).strip()
            if not name:
                continue
            answered_competencies.add(name)
            answered_competencies_lower.add(name.lower())

    confidence_by_competency = {str(key).strip().lower(): float(value) for key, value in competency_confidence.items() if str(key).strip()}

    validated_competencies: list[str] = []
    weak_competencies: list[str] = []
    evidence_table: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in competency_scores:
        competency = str(row.get("competency") or "").strip()
        if not competency:
            continue
        if role_competencies_lower and competency.lower() not in role_competencies_lower:
            # Resume technology mentions must not replace role competency scoring.
            continue
        seen.add(competency.lower())
        score = max(0.0, min(10.0, float(row.get("score") or 0.0)))
        conf = max(0.0, min(1.0, float(confidence_by_competency.get(competency.lower(), 0.0))))
        evidence_text = str(row.get("evidence") or "").strip()
        evidence_text_lower = evidence_text.lower()
        has_direct_evidence = bool(evidence_text) and "insufficient direct answer evidence" not in evidence_text_lower

        if has_direct_evidence and score >= 6.5 and conf >= 0.60:
            status = "validated"
            validated_competencies.append(competency)
        elif score <= 5.4 or (score < 6.0 and conf < 0.50):
            status = "weak"
            weak_competencies.append(competency)
        elif competency.lower() in answered_competencies_lower:
            status = "partial"
        else:
            status = "unanswered"

        evidence_table.append(
            {
                "competency": competency,
                "status": status,
                "score": round(score, 2),
                "confidence": round(conf, 2),
                "evidence": evidence_text[:220] if evidence_text else "",
            }
        )

    unanswered_competencies: list[str] = []
    for competency in role_competencies:
        if competency.lower() in seen:
            continue
        unanswered_competencies.append(competency)
        evidence_table.append(
            {
                "competency": competency,
                "status": "unanswered",
                "score": None,
                "confidence": None,
                "evidence": "",
            }
        )

    strong_answer_count = int(evidence_coverage.get("strong_answers_count") or 0)
    if strong_answer_count <= 0:
        strong_answer_count = sum(
            1
            for item in per_question_analysis
            if float(item.get("answer_quality") or 0.0) >= 7.0
            and str(item.get("depth") or "").strip().lower() in {"strong", "expert"}
        )

    case_depth_ratio = max(0.0, min(1.0, float(evidence_coverage.get("case_depth_ratio") or 0.0)))
    if case_depth_ratio <= 0.0 and per_question_analysis:
        depth_scale = {"none": 0.0, "surface": 0.25, "adequate": 0.55, "strong": 0.8, "expert": 1.0}
        depth_values = [depth_scale.get(str(item.get("depth", "surface")).lower(), 0.25) for item in per_question_analysis]
        case_depth_ratio = max(0.0, min(1.0, sum(depth_values) / max(1, len(depth_values))))

    completed_scenarios = {
        str(item).strip()
        for item in interview_meta.get("qa_completed_scenarios", []) or []
        if str(item).strip()
    }
    if completed_scenarios:
        has_completed_scenario_with_strong_evidence = case_depth_ratio >= 0.55 and strong_answer_count >= 1
    else:
        has_completed_scenario_with_strong_evidence = case_depth_ratio >= 0.70 and strong_answer_count >= 2

    strategy_keywords = (
        "strategy",
        "architecture",
        "architect",
        "архитект",
        "roadmap",
        "ownership",
        "process",
        "систем",
        "масштаб",
        "scale",
        "trade-off",
        "компромисс",
        "prevention",
        "предотвращ",
        "governance",
    )
    has_strategy_ownership_evidence = any(
        any(keyword in str(item.get("evidence") or "").lower() for keyword in strategy_keywords)
        and float(item.get("answer_quality") or 0.0) >= 7.0
        and str(item.get("depth") or "").strip().lower() in {"strong", "expert"}
        for item in per_question_analysis
    )

    return {
        "role_competencies": role_competencies,
        "answered_competencies": sorted(answered_competencies),
        "validated_competencies": sorted(set(validated_competencies)),
        "weak_competencies": sorted(set(weak_competencies)),
        "unanswered_competencies": sorted(set(unanswered_competencies)),
        "evidence_table": evidence_table,
        "strong_answer_count": strong_answer_count,
        "case_depth_ratio": round(case_depth_ratio, 2),
        "has_completed_scenario_with_strong_evidence": has_completed_scenario_with_strong_evidence,
        "has_strategy_ownership_evidence": has_strategy_ownership_evidence,
    }


def _derive_proficiency_profile(
    *,
    target_role: str = "backend_engineer",
    overall_score: float | None,
    hard_skills_score: float | None,
    problem_solving_score: float | None,
    communication_score: float | None,
    overall_confidence: float | None,
    language: str,
    confidence_verdict: str | None = None,
    validated_competencies_count: int | None = None,
    has_completed_scenario_with_strong_evidence: bool = False,
    has_strategy_ownership_evidence: bool = False,
    interview_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = max(0.0, min(10.0, float(overall_score or 0.0)))
    conf = max(0.0, min(1.0, float(overall_confidence or 0.0)))
    # Base mapping: normalized 0..10 score into 15 display levels.
    display_level = int((score / 10.0) * 15.0)
    display_level = max(1, min(15, display_level))

    # Quality-aware adjustments.
    if conf >= 0.8 and (hard_skills_score or 0.0) >= 7.0 and (problem_solving_score or 0.0) >= 7.0:
        display_level += 1
    if conf < 0.45 or (communication_score or 0.0) < 4.5:
        display_level -= 1

    # Gating: keep upper Senior levels only when core dimensions are strong.
    if display_level >= 14 and (
        (hard_skills_score or 0.0) < 7.0
        or (problem_solving_score or 0.0) < 7.0
        or (communication_score or 0.0) < 6.0
    ):
        display_level = 13

    # Runtime trajectory calibration (Iteration 7):
    # use interview progression quality to nudge border cases.
    meta = interview_meta or {}
    answer_count = max(0, int(meta.get("candidate_answers_count") or 0))
    strong_count = max(0, int(meta.get("strong_answers_count") or 0))
    weak_count = max(0, int(meta.get("weak_answers_count") or 0))
    peak_tier = max(1, min(5, int(meta.get("adaptive_difficulty_tier") or 3)))
    weak_streak = max(0, int(meta.get("consecutive_weak_answers") or 0))
    strong_ratio = (strong_count / answer_count) if answer_count else 0.0
    weak_ratio = (weak_count / answer_count) if answer_count else 0.0

    trajectory_adjustment = 0
    if (
        answer_count >= 6
        and peak_tier >= 5
        and strong_ratio >= 0.55
        and conf >= 0.65
        and (hard_skills_score or 0.0) >= 6.5
        and (problem_solving_score or 0.0) >= 6.5
    ):
        display_level += 1
        trajectory_adjustment = 1
    elif answer_count >= 6 and peak_tier <= 2 and (weak_ratio >= 0.50 or weak_streak >= 3):
        display_level -= 1
        trajectory_adjustment = -1

    display_level = max(1, min(15, display_level))
    gate_reasons: list[str] = []
    normalized_role = str(target_role or "").strip().lower()
    if validated_competencies_count is not None and display_level >= 6 and validated_competencies_count < 3:
        display_level = min(display_level, 5)
        gate_reasons.append("middle_requires_3_validated_competencies")
    if validated_competencies_count is not None and display_level >= 9 and not has_completed_scenario_with_strong_evidence:
        display_level = min(display_level, 8)
        gate_reasons.append("strong_middle_requires_completed_scenario_with_strong_evidence")
    if validated_competencies_count is not None and display_level >= 11 and not has_strategy_ownership_evidence:
        display_level = min(display_level, 10)
        gate_reasons.append("senior_requires_strategy_or_system_ownership_evidence")
    if (
        validated_competencies_count is not None
        and normalized_role == "qa_engineer"
        and validated_competencies_count < 3
        and display_level > 5
    ):
        display_level = 5
        if "middle_requires_3_validated_competencies" not in gate_reasons:
            gate_reasons.append("qa_middle_requires_3_validated_competencies")

    band_key, label = _proficiency_label_from_level(display_level, language)

    # Keep internal SFIA-style coarse banding alongside UI label.
    if display_level <= 2:
        sfia_band = "sfia_1"
    elif display_level <= 4:
        sfia_band = "sfia_2"
    elif display_level <= 6:
        sfia_band = "sfia_3"
    elif display_level <= 9:
        sfia_band = "sfia_4"
    elif display_level <= 11:
        sfia_band = "sfia_5"
    elif display_level <= 14:
        sfia_band = "sfia_6"
    else:
        sfia_band = "sfia_7"

    return {
        "proficiency_level": float(display_level),
        "proficiency_band": band_key,
        "proficiency_label": label,
        "sfia_band": sfia_band,
        "raw_overall_score": round(score, 2),
        "confidence": round(conf, 3),
        "confidence_verdict": str(confidence_verdict or _confidence_verdict_for_value(conf)),
        "validated_competencies_count": (
            int(validated_competencies_count)
            if validated_competencies_count is not None
            else None
        ),
        "has_completed_scenario_with_strong_evidence": bool(has_completed_scenario_with_strong_evidence),
        "has_strategy_ownership_evidence": bool(has_strategy_ownership_evidence),
        "gate_reasons": gate_reasons,
        "trajectory_adjustment": trajectory_adjustment,
    }


def _build_scoring_v2_human_followup_questions(
    *,
    language: str,
    weak_competencies: list[str],
    unanswered_competencies: list[str],
) -> list[str]:
    is_ru = str(language).lower().startswith("ru")
    questions: list[str] = []

    for competency in weak_competencies[:2]:
        if is_ru:
            questions.append(
                f"По компетенции «{competency}»: разберите один рабочий кейс в формате контекст → ваши действия → результат и как проверяли успех."
            )
        else:
            questions.append(
                f"For competency '{competency}', walk through one real case: context → your actions → outcome and validation method."
            )

    for competency in unanswered_competencies[:2]:
        if is_ru:
            questions.append(
                f"По теме «{competency}» не хватило сигнала. Какую конкретную задачу вы решали, какой подход выбрали и почему?"
            )
        else:
            questions.append(
                f"We need stronger signal for '{competency}'. Which concrete task did you solve, what approach did you choose, and why?"
            )

    return questions[:4]


def _apply_scoring_v2_recommendation_policy(
    *,
    result: AssessmentResult,
    confidence_verdict: str,
    validated_competencies_count: int,
) -> AssessmentResult:
    recommendation_rank = {"no": 0, "maybe": 1, "yes": 2, "strong_yes": 3}
    max_allowed = "strong_yes"

    reasons = []
    if isinstance(result.full_report_json, dict):
        reasons = list(result.full_report_json.get("recommendation_gate_reasons") or [])

    if confidence_verdict != "normal":
        max_allowed = "maybe"
    if validated_competencies_count < 3:
        max_allowed = min((max_allowed, "maybe"), key=lambda item: recommendation_rank[item])
        reason = "middle_or_higher_requires_at_least_3_validated_competencies"
        if reason not in reasons:
            reasons.append(reason)

    if recommendation_rank.get(result.hiring_recommendation, 1) > recommendation_rank.get(max_allowed, 1):
        result.hiring_recommendation = max_allowed

    if isinstance(result.full_report_json, dict):
        result.full_report_json["hiring_recommendation"] = result.hiring_recommendation
        result.full_report_json["recommendation_gate_reasons"] = reasons
    return result

_ROLE_BASE_QUESTION_BUDGET = {
    "backend_engineer": 20,
    "devops_engineer": 20,
    "data_scientist": 20,
    "frontend_engineer": 18,
    "mobile_engineer": 18,
    "qa_engineer": 17,
    "product_manager": 16,
    "designer": 16,
}
_ROLE_MAX_QUESTION_CAP = {
    "backend_engineer": 40,
    "devops_engineer": 40,
    "data_scientist": 40,
    "frontend_engineer": 36,
    "mobile_engineer": 36,
    "qa_engineer": 34,
    "product_manager": 32,
    "designer": 30,
}
_ROLE_MIN_QUESTION_FLOOR = {
    "backend_engineer": 10,
    "devops_engineer": 10,
    "data_scientist": 10,
    "frontend_engineer": 9,
    "mobile_engineer": 9,
    "qa_engineer": 10,
    "product_manager": 8,
    "designer": 8,
}
_QA_MIN_CASE_QUESTIONS = 6
_QA_MIN_SCENARIO_CASES = 2
_QA_MIN_TECHNICAL_SIGNAL_PCT = 60.0
_ADAPTIVE_MIN_QUESTIONS_FLOOR = 10
_ADAPTIVE_EXTENSION_STEP = 4
_INTERVIEW_SENIORITY_LEVELS = {"junior", "middle", "senior"}
_DEFAULT_SYNC_REPORT_GENERATION_TIMEOUT_SECONDS = 8.0
_DEFAULT_ASSESSMENT_TIMEOUT_SECONDS = 25.0
_DEFAULT_REPORT_MAX_AUTO_RETRIES = 3
_DEFAULT_REPORT_RETRY_BASE_BACKOFF_SECONDS = 2
_DEFAULT_REPORT_RETRY_MAX_BACKOFF_SECONDS = 12
_DEFAULT_REPORT_LOCK_STALE_SECONDS = 300
_REPORT_DIAGNOSTIC_STATUSES = {"pending", "processing", "ready", "failed"}
_REPORT_ATTEMPT_PHASES = {"finish_sync", "async_worker", "manual_retry"}
_MEMORY_ACTION_MARKERS = (
    "использ",
    "настро",
    "оптимиз",
    "проектир",
    "реализ",
    "внедр",
    "deployed",
    "configured",
    "designed",
    "implemented",
    "optimized",
    "built",
    "debug",
)
_REPORT_GENERATION_TASKS: set[uuid.UUID] = set()
_REPORT_PIPELINE_METRICS: defaultdict[str, int] = defaultdict(int)

_PROCTORING_POLICY_MODES = {"observe_only", "strict_flagging"}
_EVENT_SEVERITIES = {"info", "medium", "high"}
_STRICT_MEDIUM_EVENTS = {
    "paste_detected",
    "tab_switch",
    "screen_share_stopped",
    "screen_permission_denied",
    "camera_permission_denied",
    "microphone_permission_denied",
    "recording_upload_failed",
}
_STRICT_HIGH_EVENTS = {
    "multiple_faces_detected",
    "camera_stream_lost",
}

logger = logging.getLogger(__name__)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sync_report_generation_timeout_seconds() -> float:
    value = _safe_float(
        getattr(settings, "REPORT_SYNC_GENERATION_TIMEOUT_SECONDS", None),
        _DEFAULT_SYNC_REPORT_GENERATION_TIMEOUT_SECONDS,
    )
    return max(value, 1.0)


def _assessment_timeout_seconds() -> float:
    value = _safe_float(
        getattr(settings, "REPORT_ASSESSMENT_TIMEOUT_SECONDS", None),
        _DEFAULT_ASSESSMENT_TIMEOUT_SECONDS,
    )
    return max(value, 1.0)


def _report_max_auto_retries() -> int:
    value = _safe_int(
        getattr(settings, "REPORT_MAX_AUTO_RETRIES", None),
        _DEFAULT_REPORT_MAX_AUTO_RETRIES,
    )
    return max(value, 1)


def _report_retry_base_backoff_seconds() -> int:
    value = _safe_int(
        getattr(settings, "REPORT_RETRY_BASE_BACKOFF_SECONDS", None),
        _DEFAULT_REPORT_RETRY_BASE_BACKOFF_SECONDS,
    )
    return max(value, 1)


def _report_retry_max_backoff_seconds() -> int:
    configured_max = _safe_int(
        getattr(settings, "REPORT_RETRY_MAX_BACKOFF_SECONDS", None),
        _DEFAULT_REPORT_RETRY_MAX_BACKOFF_SECONDS,
    )
    return max(configured_max, _report_retry_base_backoff_seconds())


def _report_lock_stale_seconds() -> int:
    value = _safe_int(
        getattr(settings, "REPORT_LOCK_STALE_SECONDS", None),
        _DEFAULT_REPORT_LOCK_STALE_SECONDS,
    )
    return max(value, 1)


def _increment_report_pipeline_metric(metric_name: str, amount: int = 1) -> int:
    _REPORT_PIPELINE_METRICS[metric_name] += amount
    return _REPORT_PIPELINE_METRICS[metric_name]


def _log_report_pipeline_event(
    stage: str,
    *,
    interview_id: uuid.UUID,
    **fields: Any,
) -> None:
    payload = {
        "stage": stage,
        "interview_id": str(interview_id),
        "ts": datetime.utcnow().isoformat(),
        **fields,
    }
    logger.info("report_pipeline %s", json.dumps(payload, sort_keys=True, default=str))


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _compute_report_retry_backoff_seconds(attempt_number: int) -> int:
    base_backoff = _report_retry_base_backoff_seconds()
    max_backoff = _report_retry_max_backoff_seconds()
    if attempt_number <= 0:
        return base_backoff
    return min(
        base_backoff * (2 ** (attempt_number - 1)),
        max_backoff,
    )


def _next_report_diagnostics(
    current: dict | None,
    *,
    phase: str,
    status: str,
    error: str | None = None,
    next_retry_at: str | None = None,
) -> dict:
    now_iso = datetime.utcnow().isoformat()
    diagnostics = dict(current or {})
    increment_attempt = (
        status == "processing"
        and (
            phase in _REPORT_ATTEMPT_PHASES
            or phase.startswith("async_worker_attempt_")
        )
        and diagnostics.get("last_phase") != phase
    )
    if increment_attempt:
        diagnostics["attempt_count"] = _safe_int(diagnostics.get("attempt_count"), 0) + 1
        diagnostics["last_started_at"] = now_iso
    diagnostics["max_attempts"] = _report_max_auto_retries()
    diagnostics["last_phase"] = phase
    diagnostics["last_status"] = status
    diagnostics["last_transition_at"] = now_iso
    diagnostics["next_retry_at"] = next_retry_at
    if error:
        diagnostics["last_error"] = str(error)[:600]
        diagnostics["last_error_at"] = now_iso
    elif status == "ready":
        diagnostics["last_error"] = None
        diagnostics["last_error_at"] = None
        diagnostics["last_completed_at"] = now_iso
    return diagnostics


def _update_report_diagnostics(
    interview: Interview,
    *,
    phase: str,
    status: str,
    error: str | None = None,
    next_retry_at: str | None = None,
) -> None:
    state = dict(interview.interview_state or {})
    current_diag = state.get("report_diagnostics")
    if not isinstance(current_diag, dict):
        current_diag = {}
    state["report_diagnostics"] = _next_report_diagnostics(
        current_diag,
        phase=phase,
        status=status,
        error=error,
        next_retry_at=next_retry_at,
    )
    interview.interview_state = state


def _read_report_diagnostics(interview: Interview) -> dict[str, Any] | None:
    state = interview.interview_state if isinstance(interview.interview_state, dict) else {}
    raw = state.get("report_diagnostics")
    if not isinstance(raw, dict):
        return None
    last_status = raw.get("last_status")
    if last_status not in _REPORT_DIAGNOSTIC_STATUSES:
        last_status = None
    return {
        "attempt_count": _safe_int(raw.get("attempt_count"), 0),
        "max_attempts": _safe_int(raw.get("max_attempts"), _report_max_auto_retries()),
        "last_phase": raw.get("last_phase"),
        "last_status": last_status,
        "last_started_at": raw.get("last_started_at"),
        "last_completed_at": raw.get("last_completed_at"),
        "last_transition_at": raw.get("last_transition_at"),
        "next_retry_at": raw.get("next_retry_at"),
        "last_error": raw.get("last_error"),
        "last_error_at": raw.get("last_error_at"),
    }


async def _try_acquire_report_generation_lock(
    db: AsyncSession,
    interview_id: uuid.UUID,
    *,
    owner: str,
) -> bool:
    interview = await db.scalar(
        select(Interview).where(Interview.id == interview_id).with_for_update()
    )
    if not interview:
        await db.rollback()
        return False

    now = datetime.utcnow()
    state = dict(interview.interview_state or {})
    lock_payload = state.get("report_generation_lock")
    if isinstance(lock_payload, dict):
        lock_owner = str(lock_payload.get("owner") or "")
        locked_at = _parse_iso_datetime(lock_payload.get("locked_at"))
        lock_stale_seconds = _report_lock_stale_seconds()
        lock_age_seconds = (
            (now - locked_at).total_seconds() if locked_at else lock_stale_seconds + 1
        )
        if lock_owner and lock_owner != owner and lock_age_seconds < lock_stale_seconds:
            await db.rollback()
            return False

    state["report_generation_lock"] = {
        "owner": owner,
        "locked_at": now.isoformat(),
    }
    interview.interview_state = state
    await db.commit()
    return True


async def _release_report_generation_lock(
    db: AsyncSession,
    interview_id: uuid.UUID,
    *,
    owner: str,
) -> None:
    interview = await db.scalar(
        select(Interview).where(Interview.id == interview_id).with_for_update()
    )
    if not interview:
        await db.rollback()
        return

    state = dict(interview.interview_state or {})
    lock_payload = state.get("report_generation_lock")
    if isinstance(lock_payload, dict) and str(lock_payload.get("owner") or "") == owner:
        state.pop("report_generation_lock", None)
        interview.interview_state = state
        await db.commit()
        return

    await db.rollback()


def _normalize_policy_mode(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in _PROCTORING_POLICY_MODES:
        return normalized
    configured = (settings.PROCTORING_POLICY_MODE or "").strip().lower()
    if configured in _PROCTORING_POLICY_MODES:
        return configured
    return "observe_only"


def _normalize_event_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def _normalize_event(
    raw_event: dict[str, Any],
    *,
    index: int,
    policy_mode: str,
) -> dict[str, Any]:
    event_type = str(raw_event.get("event_type") or raw_event.get("type") or "").strip().lower()
    if not event_type:
        event_type = f"event_{index + 1}"

    severity = str(raw_event.get("severity") or "info").strip().lower()
    if severity not in _EVENT_SEVERITIES:
        severity = "info"

    if policy_mode == "strict_flagging":
        if event_type in _STRICT_HIGH_EVENTS:
            severity = "high"
        elif event_type in _STRICT_MEDIUM_EVENTS and severity == "info":
            severity = "medium"

    occurred_at = _normalize_event_timestamp(
        raw_event.get("occurred_at") or raw_event.get("timestamp") or raw_event.get("time")
    )
    source = str(raw_event.get("source") or "client").strip().lower() or "client"
    details_raw = raw_event.get("details")
    details = details_raw if isinstance(details_raw, dict) else {}

    return {
        "event_type": event_type,
        "severity": severity,
        "occurred_at": occurred_at,
        "source": source,
        "details": details,
    }


def _synthesize_events_from_counters(signals: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    tab_switches = _safe_int(signals.get("tab_switches"), 0)
    paste_count = _safe_int(signals.get("paste_count"), 0)
    face_away_pct = signals.get("face_away_pct")
    speech_activity_pct = signals.get("speech_activity_pct")
    silence_pct = signals.get("silence_pct")
    long_silence_count = _safe_int(signals.get("long_silence_count"), 0)
    speech_segment_count = _safe_int(signals.get("speech_segment_count"), 0)
    response_times = signals.get("response_times")

    if tab_switches > 0:
        events.append(
            {
                "event_type": "tab_switch",
                "severity": "medium" if tab_switches >= 3 else "info",
                "occurred_at": None,
                "source": "client",
                "details": {"count": tab_switches},
            }
        )

    if paste_count > 0:
        events.append(
            {
                "event_type": "paste_detected",
                "severity": "medium" if paste_count >= 2 else "info",
                "occurred_at": None,
                "source": "client",
                "details": {"count": paste_count},
            }
        )

    if isinstance(face_away_pct, (int, float)) and face_away_pct >= 0.3:
        events.append(
            {
                "event_type": "face_away_high",
                "severity": "medium" if face_away_pct < 0.5 else "high",
                "occurred_at": None,
                "source": "client",
                "details": {"face_away_pct": round(float(face_away_pct), 3)},
            }
        )

    if isinstance(speech_activity_pct, (int, float)) and speech_activity_pct < 0.08:
        events.append(
            {
                "event_type": "speech_activity_low",
                "severity": "medium" if speech_activity_pct < 0.04 else "info",
                "occurred_at": None,
                "source": "client",
                "details": {
                    "speech_activity_pct": round(float(speech_activity_pct), 3),
                    "silence_pct": round(_safe_float(silence_pct, 0.0), 3) if silence_pct is not None else None,
                    "speech_segment_count": speech_segment_count,
                },
            }
        )

    if long_silence_count > 0:
        events.append(
            {
                "event_type": "long_silence",
                "severity": "medium" if long_silence_count >= 2 else "info",
                "occurred_at": None,
                "source": "client",
                "details": {
                    "count": long_silence_count,
                    "silence_pct": round(_safe_float(silence_pct, 0.0), 3) if silence_pct is not None else None,
                },
            }
        )

    if isinstance(response_times, list):
        suspicious_fast = [item for item in response_times if isinstance(item, dict) and float(item.get("seconds") or 0) <= 1.5]
        if suspicious_fast:
            events.append(
                {
                    "event_type": "very_fast_answers",
                    "severity": "info",
                    "occurred_at": None,
                    "source": "client",
                    "details": {"count": len(suspicious_fast)},
                }
            )

    return events


def normalize_behavioral_signals(signals: dict | None) -> dict[str, Any]:
    payload: dict[str, Any] = dict(signals or {})
    policy_mode = _normalize_policy_mode(payload.get("policy_mode"))
    raw_events = payload.get("events")
    normalized_events: list[dict[str, Any]] = []

    if isinstance(raw_events, list):
        for idx, item in enumerate(raw_events):
            if isinstance(item, dict):
                normalized_events.append(_normalize_event(item, index=idx, policy_mode=policy_mode))

    synthesized = _synthesize_events_from_counters(payload)
    existing_types = {str(item.get("event_type") or "") for item in normalized_events}
    for idx, item in enumerate(synthesized):
        normalized = _normalize_event(item, index=len(normalized_events) + idx, policy_mode=policy_mode)
        event_type = str(normalized.get("event_type") or "")
        if event_type in existing_types:
            continue
        normalized_events.append(normalized)
        existing_types.add(event_type)

    payload["policy_mode"] = policy_mode
    payload["events"] = normalized_events
    payload["captured_at"] = datetime.utcnow().isoformat()
    return payload


def get_proctoring_timeline_payload(signals: dict | None) -> dict[str, Any]:
    normalized = normalize_behavioral_signals(signals)
    events = list(normalized.get("events", []))
    high_count = sum(1 for event in events if event.get("severity") == "high")
    medium_count = sum(1 for event in events if event.get("severity") == "medium")
    speech_activity_pct = normalized.get("speech_activity_pct")
    silence_pct = normalized.get("silence_pct")
    long_silence_count = _safe_int(normalized.get("long_silence_count"), 0)
    speech_segment_count = _safe_int(normalized.get("speech_segment_count"), 0)

    if high_count > 0:
        risk_level = "high"
    elif medium_count >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "policy_mode": normalized.get("policy_mode", "observe_only"),
        "risk_level": risk_level,
        "total_events": len(events),
        "high_severity_count": high_count,
        "speech_activity_pct": round(_safe_float(speech_activity_pct), 3) if speech_activity_pct is not None else None,
        "silence_pct": round(_safe_float(silence_pct), 3) if silence_pct is not None else None,
        "long_silence_count": long_silence_count,
        "speech_segment_count": speech_segment_count,
        "events": events,
    }


def _normalize_interview_seniority(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in _INTERVIEW_SENIORITY_LEVELS:
        return normalized
    return None


def _estimate_dynamic_question_budget(
    *,
    target_role: str,
    resume_profile: dict | None,
    selected_seniority: str | None = None,
) -> tuple[int, int, int]:
    """Return (initial_max_questions, role_max_cap, min_questions_before_early_stop)."""
    role_cap = _ROLE_MAX_QUESTION_CAP.get(target_role, 32)
    role_floor = _ROLE_MIN_QUESTION_FLOOR.get(target_role, _ADAPTIVE_MIN_QUESTIONS_FLOOR)
    qa_v2_mode = target_role == "qa_engineer" and _is_interview_engine_v2_enabled(role=target_role)
    qa_v2_floor = 10
    qa_v2_cap = 10
    if qa_v2_mode:
        role_floor = qa_v2_floor
        role_cap = min(role_cap, qa_v2_cap)
    profile = resume_profile or {}
    normalized_selected_seniority = _normalize_interview_seniority(selected_seniority)

    technologies = list(profile.get("technologies", []) or [])
    project_highlights = list(profile.get("project_highlights", []) or [])
    experience_years = profile.get("experience_years")
    seniority_hint = normalized_selected_seniority or str(profile.get("seniority_hint") or "").strip().lower()

    has_resume_signal = bool(
        technologies
        or project_highlights
        or experience_years is not None
        or seniority_hint
    )
    if not has_resume_signal:
        # Preserve legacy behavior for sparse/noisy resumes except QA:
        # QA interviews keep a stable minimum depth to avoid premature behavioral closure.
        if target_role == "qa_engineer":
            initial = role_floor if qa_v2_mode else max(role_floor, _ADAPTIVE_MIN_QUESTIONS_FLOOR)
            return initial, role_cap, min(role_floor, initial)
        initial = MAX_QUESTIONS
        return initial, initial, initial + 1

    budget = qa_v2_floor if qa_v2_mode else _ROLE_BASE_QUESTION_BUDGET.get(target_role, 16)

    years = _safe_int(experience_years, 0)
    if years >= 10:
        budget += 8
    elif years >= 7:
        budget += 6
    elif years >= 5:
        budget += 4
    elif years >= 3:
        budget += 2

    if normalized_selected_seniority == "junior":
        budget -= 8
        role_cap = min(role_cap, 16)
    elif normalized_selected_seniority == "middle":
        role_cap = min(role_cap, 24)
    elif normalized_selected_seniority == "senior":
        budget += 2
    elif seniority_hint in {"staff", "senior"}:
        budget += 3
    elif seniority_hint == "middle":
        budget += 1

    # Richer resumes usually need wider competency coverage.
    budget += min(6, len(set(technologies)))
    budget += min(4, len(project_highlights))

    initial = max(role_floor, min(role_cap, budget))
    return initial, role_cap, min(role_floor, initial)


def _extract_candidate_memory_fact(
    *,
    answer: str,
    answer_class: str,
    new_techs: set[str],
) -> str:
    normalized = " ".join(answer.strip().split())
    if not normalized:
        return ""

    sentences: list[tuple[int, str]] = []
    for raw_sentence in re.split(r"[.!?]+", normalized):
        sentence = raw_sentence.strip(" ,;:-")
        if len(sentence.split()) < 5:
            continue
        lowered = sentence.lower()
        score = 0
        if new_techs and any(tech in lowered for tech in new_techs):
            score += 3
        if any(marker in lowered for marker in _MEMORY_ACTION_MARKERS):
            score += 2
        score += min(2, len(sentence.split()) // 12)
        sentences.append((score, sentence))

    if sentences:
        sentences.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        fact = sentences[0][1]
    else:
        fact = " ".join(normalized.split()[:26])

    if answer_class == "no_experience_honest":
        fact = f"Honest gap noted: {fact}"

    if new_techs:
        tech_hint = ", ".join(sorted(new_techs)[:3])
        fact = f"{fact} [tech: {tech_hint}]"

    if len(fact) > 180:
        fact = f"{fact[:180].rstrip()}..."
    return fact


def _append_candidate_memory(
    previous_memory: list[str],
    *,
    answer: str,
    answer_class: str,
    answer_relevance: str,
    new_techs: set[str],
) -> list[str]:
    memory = [str(item).strip() for item in previous_memory if str(item).strip()]

    # Ignore low-signal noise unless it adds concrete technology context.
    if _is_noise_or_nonsense_answer(answer) and not new_techs:
        return memory[-12:]
    if answer_class in {"generic", "evasive"} and not new_techs:
        return memory[-12:]
    if (
        answer_relevance == "low"
        and len(answer.strip().split()) < 12
        and not new_techs
        and answer_class != "no_experience_honest"
    ):
        return memory[-12:]

    fact = _extract_candidate_memory_fact(
        answer=answer,
        answer_class=answer_class,
        new_techs=new_techs,
    )
    if not fact:
        return memory[-12:]

    fact_fp = _normalize_answer_fingerprint(fact)
    if not fact_fp:
        return memory[-12:]

    deduped: list[str] = []
    seen_fps: set[str] = set()
    for item in memory + [fact]:
        fp = _normalize_answer_fingerprint(item)
        if not fp or fp in seen_fps:
            continue
        deduped.append(item)
        seen_fps.add(fp)

    return deduped[-12:]


def _topic_label_for_summary(topic: dict | None) -> str:
    data = topic or {}
    block = str(data.get("block") or "").strip()
    if block:
        return block
    competencies = [str(item).strip() for item in data.get("competencies", []) if item]
    if competencies:
        return competencies[0]
    phase = str(data.get("phase") or "").strip()
    return phase or "topic"


def _append_transcript_summary(
    previous_summary: list[str],
    *,
    topic: dict | None,
    answer: str,
    answer_class: str,
    answer_relevance: str,
    is_clarification_request: bool,
) -> list[str]:
    summary = [str(item).strip() for item in previous_summary if str(item).strip()]
    if is_clarification_request:
        return summary[-20:]
    normalized_answer = " ".join((answer or "").strip().split())
    if not normalized_answer:
        return summary[-20:]
    if answer_class in {"generic", "evasive"} and answer_relevance == "low" and len(normalized_answer.split()) < 8:
        return summary[-20:]
    label = _topic_label_for_summary(topic)
    snippet = normalized_answer
    if len(snippet) > 140:
        snippet = f"{snippet[:140].rstrip()}..."
    entry = f"{label}: {snippet}"
    fp = _normalize_answer_fingerprint(entry)
    if fp and all(_normalize_answer_fingerprint(item) != fp for item in summary):
        summary.append(entry)
    return summary[-20:]


def _adapt_question_budget(
    *,
    current_max_questions: int,
    current_question_count: int,
    answer_count: int,
    strong_answers_count: int,
    weak_answers_count: int,
    low_relevance_answers_count: int,
    consecutive_weak_answers: int,
    min_questions_before_early_stop: int,
    role_max_cap: int,
    nonsense_answers_count: int = 0,
) -> tuple[int, bool, str | None]:
    if answer_count <= 0:
        return current_max_questions, False, None

    weak_ratio = weak_answers_count / answer_count
    strong_ratio = strong_answers_count / answer_count
    low_relevance_ratio = low_relevance_answers_count / answer_count
    remaining_questions = max(current_max_questions - current_question_count, 0)

    # Early stop for consistently weak sessions: keep interview short and let report generation proceed.
    if (
        answer_count >= min_questions_before_early_stop
        and current_question_count >= min_questions_before_early_stop
        and weak_ratio >= 0.68
        and (low_relevance_ratio >= 0.35 or consecutive_weak_answers >= 4)
        and consecutive_weak_answers >= 2
        and strong_answers_count <= max(1, answer_count // 5)
    ):
        return max(current_question_count, 1), True, "early_stop_low_signal"

    # Fail-fast for sessions that are mostly noise/non-informative text.
    if (
        answer_count >= max(4, min_questions_before_early_stop - 2)
        and nonsense_answers_count >= max(2, answer_count // 3)
        and current_question_count >= max(4, min_questions_before_early_stop - 2)
        and consecutive_weak_answers >= 2
    ):
        return max(current_question_count, 1), True, "early_stop_nonsense_signal"

    # Near the planned end, extend depth for strong candidates (up to role cap).
    if (
        current_question_count >= max(current_max_questions - 1, 1)
        and current_max_questions < role_max_cap
        and answer_count >= 6
        and strong_ratio >= 0.55
        and low_relevance_ratio <= 0.30
        and consecutive_weak_answers == 0
    ):
        extended = min(role_max_cap, current_max_questions + _ADAPTIVE_EXTENSION_STEP)
        if extended > current_max_questions:
            return extended, False, "extended_for_depth"

    # Extend proactively when session quality is strong and we are close to current limit.
    if (
        answer_count >= 4
        and current_max_questions < role_max_cap
        and remaining_questions <= 4
        and strong_ratio >= 0.50
        and weak_ratio <= 0.45
        and low_relevance_ratio <= 0.28
        and consecutive_weak_answers == 0
    ):
        extension_step = _ADAPTIVE_EXTENSION_STEP + (
            2 if strong_ratio >= 0.72 and answer_count >= 8 else 0
        )
        extended = min(role_max_cap, current_max_questions + extension_step)
        if extended > current_max_questions:
            return extended, False, "extended_for_strong_signal"

    # Compress plan earlier for mixed/weak signals instead of waiting until the very end.
    if (
        answer_count >= 4
        and current_max_questions > min_questions_before_early_stop
        and weak_ratio >= 0.62
        and strong_ratio <= 0.25
        and (low_relevance_ratio >= 0.25 or consecutive_weak_answers >= 2)
    ):
        reduced = max(
            min_questions_before_early_stop,
            min(current_max_questions, current_question_count + 2),
        )
        if reduced < current_max_questions:
            return reduced, False, "reduced_for_mixed_low_signal"

    if (
        answer_count >= 4
        and current_max_questions > min_questions_before_early_stop
        and nonsense_answers_count >= 2
        and consecutive_weak_answers >= 2
    ):
        reduced = max(
            min_questions_before_early_stop,
            min(current_max_questions, current_question_count + 1),
        )
        if reduced < current_max_questions:
            return reduced, False, "reduced_for_nonsense_signal"

    # Compress overly long plans when signal is consistently weak.
    if (
        answer_count >= 6
        and current_max_questions > min_questions_before_early_stop
        and weak_ratio >= 0.78
        and (low_relevance_ratio >= 0.30 or consecutive_weak_answers >= 3)
        and strong_answers_count == 0
    ):
        reduced = max(
            min_questions_before_early_stop,
            min(current_max_questions, current_question_count + 2),
        )
        if reduced < current_max_questions:
            return reduced, False, "reduced_for_low_signal"

    return current_max_questions, False, None


def _merge_topic_signal(existing: str | None, incoming: str) -> str:
    if not existing:
        return incoming
    return incoming if _ANSWER_CLASS_PRIORITY.get(incoming, 0) >= _ANSWER_CLASS_PRIORITY.get(existing, 0) else existing


def _normalize_answer_fingerprint(text: str) -> str:
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    return " ".join(tokens[:40])


def _normalize_answer_history(previous_answers: list[dict] | list[str]) -> list[dict]:
    normalized: list[dict] = []
    for item in previous_answers:
        if isinstance(item, dict):
            normalized.append(
                {
                    "content": str(item.get("content", "")),
                    "topic_index": int(item.get("topic_index", -1) or -1),
                }
            )
        else:
            normalized.append({"content": str(item), "topic_index": -1})
    return normalized


def _append_answer_history(previous_answers: list[dict] | list[str], answer: str, topic_index: int) -> list[dict]:
    normalized = _normalize_answer_history(previous_answers)
    normalized.append({"content": answer, "topic_index": topic_index})
    return normalized[-10:]


def _is_noise_or_nonsense_answer(answer: str) -> bool:
    normalized = " ".join((answer or "").strip().lower().split())
    if not normalized:
        return False

    if any(marker in normalized for marker in _NONSENSE_MARKERS):
        return True

    if re.search(r"(.)\1{5,}", normalized):
        return True

    words = [token.lower() for token in _TOKEN_RE.findall(normalized)]
    if len(words) < 6:
        return False

    unique_words = set(words)
    unique_ratio = len(unique_words) / max(1, len(words))
    if len(words) >= 10 and unique_ratio <= 0.30:
        return True

    filler_count = sum(1 for token in words if token in _FILLER_NOISE_TOKENS)
    if len(words) >= 8 and filler_count / len(words) >= 0.45:
        return True

    return False


def _is_ambiguous_short_question(question: str, *, language: str) -> bool:
    compact = " ".join((question or "").strip().split())
    if not compact:
        return False
    words = compact.split()
    if len(words) <= 2:
        return True
    if len(words) > 12:
        return False

    pattern = _AMBIGUOUS_SHORT_QUESTION_EN_RE if language == "en" else _AMBIGUOUS_SHORT_QUESTION_RE
    if pattern.search(compact):
        return True

    lowered = compact.lower()
    if language == "en":
        return lowered in {
            "how did you do it?",
            "how did you solve it?",
            "how did you fix it?",
            "what?",
            "who?",
        }
    return lowered in {
        "как вы это делали?",
        "как вы это решали?",
        "как вы их решали?",
        "как вы их делали?",
        "как вы их диагностировали?",
        "кого?",
        "чего?",
        "что?",
    }


def _is_clarification_request(answer: str) -> bool:
    compact = " ".join((answer or "").strip().lower().split())
    if not compact:
        return False
    if len(compact.split()) > 14:
        return False
    if compact in {"кого", "кого?", "чего", "чего?", "что", "что?"}:
        return True
    if compact in {"не понял", "непонятно", "уточните", "поясните", "повторите", "what?", "who?"}:
        return True
    return bool(_CLARIFICATION_REQUEST_RE.search(compact))


def _is_move_on_request(answer: str) -> bool:
    compact = " ".join((answer or "").strip().lower().split())
    if not compact:
        return False
    # Candidates often phrase "move on" with a short explanation.
    if len(compact.split()) > 28:
        return False
    return bool(_MOVE_ON_REQUEST_RE.search(compact))


def classify_candidate_intent_v2(answer: str) -> dict[str, Any]:
    result = classify_candidate_intent(answer, context={})
    normalized_intent = str(result.get("intent") or "answer")
    legacy_intent = normalized_intent
    if normalized_intent == "challenge_interviewer":
        legacy_intent = "meta_question"
    elif normalized_intent == "request_resume_focus":
        legacy_intent = "request_personalized_to_resume"
    elif normalized_intent == "dont_know":
        legacy_intent = "refusal_or_no_knowledge"
    elif normalized_intent == "request_example":
        legacy_intent = "clarification_request"

    return {
        "intent": legacy_intent,
        "should_count_as_answer": bool(result.get("should_count_as_answer", True)),
        "should_advance_scenario": bool(result.get("should_advance_scenario", True)),
    }


def _is_weak_general_signal_answer(answer: str) -> bool:
    compact = " ".join((answer or "").strip().lower().split())
    if not compact:
        return False
    if _RUNTIME_GENERAL_WEAK_RE.search(compact):
        return True
    # Very short and generic operational keywords without details.
    tokens = [token.lower() for token in _TOKEN_RE.findall(compact)]
    if len(tokens) <= 4 and any(token in {"логи", "логи.", "api", "апи", "везде", "проверю", "посмотрю"} for token in tokens):
        return True
    return False


def _build_pressure_followup_question(
    *,
    language: str,
    answer: str,
) -> str:
    lowered = " ".join((answer or "").strip().lower().split())
    is_en = str(language).lower().startswith("en")
    if "везде" in lowered or "everywhere" in lowered:
        return (
            "Давайте конкретнее: назовите первые 2 места проверки и что именно ожидаете там увидеть?"
            if not is_en
            else "Let's be concrete: name the first 2 places you would check and what exactly you expect to see there?"
        )
    if "лог" in lowered or "log" in lowered:
        return (
            "Какие именно логи и по какому идентификатору будете искать событие: user id, request id, transaction id или correlation id?"
            if not is_en
            else "Which exact logs will you check, and by which identifier: user id, request id, transaction id, or correlation id?"
        )
    if "api" in lowered or "апи" in lowered or "endpoint" in lowered:
        return (
            "Какой endpoint и какие 2 проверки в ответе API вы сделаете первыми, чтобы локализовать проблему?"
            if not is_en
            else "Which endpoint and which 2 checks in the API response would you do first to localize the issue?"
        )
    if "не знаю" in lowered or "незнаю" in lowered or "don't know" in lowered:
        return (
            "Ок, базовый вариант: если деньги списались, но статус ошибка, где проще всего подтвердить факт операции — в ответе API, логах сервиса или статусе транзакции?"
            if not is_en
            else "Okay, baseline approach: if money is deducted but status is error, where is it easiest to confirm the operation first — API response, service logs, or transaction status?"
        )
    return (
        "Давайте точнее: один конкретный шаг, один источник данных и критерий, по которому поймёте, что шаг сработал?"
        if not is_en
        else "Let's get specific: one concrete step, one data source, and one criterion that tells you the step worked?"
    )


def _sanitize_chat_question(question: str | None, *, language: str) -> str | None:
    if not question:
        return None

    compact = re.sub(r"\s+", " ", str(question)).strip()
    if not compact:
        return None

    if compact.count("?") > 1:
        fragments = [fragment.strip(" ,;:") for fragment in compact.split("?") if fragment.strip()]
        if fragments:
            compact = f"{fragments[-1]}?"

    words = compact.split()
    if len(words) > _MAX_CHAT_QUESTION_WORDS:
        compact = " ".join(words[:_MAX_CHAT_QUESTION_WORDS]).rstrip(" ,.;:!?") + "?"

    if len(compact) > 220:
        compact = compact[:220].rsplit(" ", 1)[0].rstrip(" ,.;:!?") + "?"

    if not compact.endswith("?"):
        compact = compact.rstrip(" ,.;:") + "?"

    if compact:
        compact = compact[0].upper() + compact[1:]

    lowered = compact.lower()
    has_ambiguous_reference = bool(
        re.search(r"\b(это|этих|их|them|it|that)\b", lowered)
    )

    if len(compact.split()) < 6 and has_ambiguous_reference:
        return (
            "Let's use a concrete example: a customer reports an operation error. What did you check first, what did you do personally, and how did you verify the result?"
            if language == "en"
            else "Давайте на примере: клиент сообщает об ошибке операции. Что вы проверили первым, что сделали лично вы и как подтвердили результат?"
        )

    if len(compact.split()) < 4:
        return (
            "Let's use a concrete example: a customer reports an operation error. What did you check first, what did you do personally, and how did you verify the result?"
            if language == "en"
            else "Давайте на примере: клиент сообщает об ошибке операции. Что вы проверили первым, что сделали лично вы и как подтвердили результат?"
        )
    if _is_ambiguous_short_question(compact, language=language):
        return (
            "Let's use a concrete example: a customer reports an operation error. What did you check first, what did you do personally, and how did you verify the result?"
            if language == "en"
            else "Давайте на примере: клиент сообщает об ошибке операции. Что вы проверили первым, что сделали лично вы и как подтвердили результат?"
        )

    return compact


def _is_cross_topic_reuse(answer: str, previous_answers: list[dict] | list[str], current_topic_index: int) -> bool:
    current = _normalize_answer_fingerprint(answer)
    if not current or len(current.split()) < 6:
        return False
    current_tokens = set(current.split())
    for previous in _normalize_answer_history(previous_answers)[-6:]:
        if int(previous.get("topic_index", -1)) == current_topic_index:
            continue
        prev = _normalize_answer_fingerprint(str(previous.get("content", "")))
        if not prev:
            continue
        if current == prev:
            return True
        prev_tokens = set(prev.split())
        if not prev_tokens:
            continue
        overlap = len(current_tokens & prev_tokens) / max(1, len(current_tokens | prev_tokens))
        if overlap >= 0.72:
            return True
    return False


def _question_keywords(question: str | None) -> set[str]:
    if not question:
        return set()
    return {
        token.lower()
        for token in _TOKEN_RE.findall(question)
        if len(token) > 2 and token.lower() not in _QUESTION_STOPWORDS
    }


def _answer_relevance(
    *,
    question: str | None,
    answer: str,
    new_techs: set[str],
    current_claim_target: str | None,
) -> str:
    answer_tokens = {
        token.lower()
        for token in _TOKEN_RE.findall(answer)
        if len(token) > 2 and token.lower() not in _QUESTION_STOPWORDS
    }
    if not answer_tokens:
        return "low"

    question_tokens = _question_keywords(question)
    claim_target = (current_claim_target or "").lower().strip()
    if claim_target and claim_target in new_techs:
        return "high"
    if claim_target and claim_target in answer_tokens:
        return "high"
    if claim_target and claim_target not in answer_tokens and claim_target not in new_techs:
        overlap = len(answer_tokens & question_tokens)
        return "medium" if overlap >= 2 else "low"

    overlap = len(answer_tokens & question_tokens)
    if overlap >= 3:
        return "high"
    if overlap >= 1 or new_techs:
        return "medium"
    return "low"


def evaluate_answer_runtime_v2(
    *,
    question: str | None,
    answer: str,
    transcript: list[str] | list[dict] | str | None,
    role: str,
) -> dict[str, Any]:
    normalized_question = " ".join((question or "").strip().split())
    normalized_answer = " ".join((answer or "").strip().split())
    lowered_answer = normalized_answer.lower()
    answer_words = normalized_answer.split()
    role_hint = (role or "").strip().lower()

    if isinstance(transcript, str):
        transcript_text = transcript
    elif isinstance(transcript, list):
        transcript_text = " ".join(str(item) for item in transcript)
    else:
        transcript_text = ""
    transcript_text = transcript_text.lower()

    candidate_intent = classify_candidate_intent(
        normalized_answer,
        {
            "role": role_hint,
            "current_question": normalized_question,
            "transcript_summary": transcript_text[-1500:],
        },
    )
    intent = str(candidate_intent.get("intent") or "answer")
    should_count_as_answer = bool(candidate_intent.get("should_count_as_answer", True))
    should_advance_scenario = bool(candidate_intent.get("should_advance_scenario", True))

    answer_class, _ = classify_answer(normalized_answer)
    techs = extract_mentioned_technologies(normalized_answer)
    has_example = bool(_RUNTIME_EXAMPLE_MARKERS_RE.search(normalized_answer))
    if not has_example and transcript_text:
        has_example = any(marker in transcript_text for marker in ("например", "кейс", "for example", "case"))

    role_specific_tech_markers = {
        "qa_engineer": ("тест", "test case", "bug", "дефект", "regression", "smoke", "postman", "api"),
        "backend_engineer": ("api", "sql", "index", "transaction", "latency", "redis", "kafka"),
        "frontend_engineer": ("react", "vue", "ui", "css", "a11y", "render", "bundle"),
        "devops_engineer": ("ci/cd", "kubernetes", "docker", "helm", "slo", "observability"),
    }
    role_markers = role_specific_tech_markers.get(role_hint, ())
    has_technical_detail = (
        bool(techs)
        or bool(_RUNTIME_TECHNICAL_MARKERS_RE.search(normalized_answer))
        or any(marker in lowered_answer for marker in role_markers)
    )
    has_personal_action = bool(_RUNTIME_PERSONAL_ACTION_MARKERS_RE.search(normalized_answer))
    has_result = bool(_RUNTIME_RESULT_MARKERS_RE.search(normalized_answer))
    has_tradeoff = bool(_RUNTIME_TRADEOFF_MARKERS_RE.search(normalized_answer))
    interviewer_failure = bool(_RUNTIME_INTERVIEWER_FAILURE_RE.search(normalized_answer))
    candidate_asks_clarification = bool(intent in {"clarification_request", "confusion"} or _is_clarification_request(normalized_answer))
    candidate_confusion = bool(candidate_asks_clarification or interviewer_failure)
    is_move_on = _is_move_on_request(normalized_answer)
    is_nonsense = _is_noise_or_nonsense_answer(normalized_answer)

    if intent == "dont_know":
        quality = "weak"
    elif not normalized_answer or len(answer_words) <= 2:
        quality = "no_signal"
    elif not should_count_as_answer and intent != "dont_know":
        # Clarification requests are not technical weakness; the interviewer must simplify/reframe.
        quality = "no_signal"
    elif answer_class in {"generic", "evasive"} or is_nonsense:
        quality = "weak"
    elif answer_class == "no_experience_honest":
        quality = "weak" if intent == "dont_know" else "no_signal"
    elif (
        has_example
        and has_personal_action
        and has_technical_detail
        and has_result
        and len(answer_words) >= 12
    ):
        quality = "strong"
    elif len(answer_words) < 7:
        quality = "weak"
    else:
        # Medium if at least part of evidence is present; otherwise weak.
        evidence_hits = sum(
            1 for flag in (has_example, has_personal_action, has_technical_detail, has_result) if flag
        )
        quality = "medium" if evidence_hits >= 2 else "weak"

    # Rule: generic/overly broad answers should be weak.
    if quality in {"strong", "medium"}:
        broad_markers = ("много", "разные", "как обычно", "часто", "обычно", "many", "various", "as usual")
        if any(marker in lowered_answer for marker in broad_markers) and not has_example and not has_technical_detail:
            quality = "weak"

    question_tokens = _question_keywords(normalized_question)
    answer_tokens = {
        token.lower()
        for token in _TOKEN_RE.findall(normalized_answer)
        if len(token) > 2 and token.lower() not in _QUESTION_STOPWORDS
    }
    if question_tokens and answer_tokens:
        overlap = len(question_tokens & answer_tokens)
        if overlap == 0 and quality in {"strong", "medium"} and not has_technical_detail:
            quality = "weak"

    # Rule: no concrete example -> max medium.
    if not has_example and quality == "strong":
        quality = "medium"

    # Rule: no technical details -> cannot be strong.
    if not has_technical_detail and quality == "strong":
        quality = "medium"

    base_depth_by_class = {
        "strong": 7.5,
        "medium": 5.5,
        "weak": 3.0,
        "no_signal": 1.0,
    }
    depth_score = base_depth_by_class.get(quality, 3.0)
    if has_example:
        depth_score += 1.0
    if has_personal_action:
        depth_score += 1.0
    if has_technical_detail:
        depth_score += 1.5
    if has_result:
        depth_score += 1.2
    if has_tradeoff:
        depth_score += 0.8
    if len(answer_words) >= 28:
        depth_score += 1.0
    if len(answer_words) < 10:
        depth_score -= 1.0

    # Rule: no technical details -> depth <= 5.
    if not has_technical_detail:
        depth_score = min(depth_score, 5.0)

    depth_score = round(max(0.0, min(10.0, depth_score)), 1)

    if not normalized_answer:
        evidence_type = "none"
    elif has_result:
        evidence_type = "measurable_result"
    elif has_tradeoff:
        evidence_type = "tradeoff"
    elif has_technical_detail and has_personal_action:
        evidence_type = "implementation_detail"
    elif has_example:
        evidence_type = "example"
    else:
        evidence_type = "generic"

    if is_move_on:
        recommended_next_action = "switch_topic"
    elif intent == "meta_question":
        recommended_next_action = "simplify"
    elif intent == "request_resume_focus":
        recommended_next_action = "follow_up"
    elif candidate_confusion:
        recommended_next_action = "simplify"
    elif quality == "weak":
        recommended_next_action = "follow_up"
    elif quality == "medium":
        recommended_next_action = "continue_scenario" if has_example and has_technical_detail else "follow_up"
    else:
        recommended_next_action = "switch_topic"

    needs_followup = recommended_next_action in {"follow_up", "simplify", "continue_scenario"}
    if recommended_next_action == "simplify":
        followup_type = "simplify"
    elif recommended_next_action == "continue_scenario":
        followup_type = "deep_dive"
    elif recommended_next_action == "follow_up":
        followup_type = "clarify" if not has_example else "deep_dive"
    else:
        followup_type = "switch_topic"

    return {
        "quality": quality,
        "candidate_intent": {
            "intent": intent,
            "should_count_as_answer": should_count_as_answer,
            "should_advance_scenario": should_advance_scenario,
        },
        "evidence_type": evidence_type,
        "has_concrete_example": has_example,
        "has_personal_action": has_personal_action,
        "has_technical_detail": has_technical_detail,
        "has_result": has_result,
        "candidate_confusion": candidate_confusion,
        "candidate_asks_clarification": candidate_asks_clarification,
        "answer_score": depth_score,
        "recommended_next_action": recommended_next_action,
        # Backward-compatible fields expected by v1 decision engine.
        "has_example": has_example,
        "depth_score": depth_score,
        "needs_followup": needs_followup,
        "followup_type": followup_type,
        "interviewer_failure": interviewer_failure,
        "should_count_as_answer": should_count_as_answer,
        "should_advance_scenario": should_advance_scenario,
        "pressure_followup_required": bool(
            should_count_as_answer
            and quality in {"weak", "no_signal"}
            and _is_weak_general_signal_answer(normalized_answer)
        ),
    }


def evaluate_answer_runtime(
    *,
    question: str | None,
    answer: str,
    transcript: list[str] | list[dict] | str | None,
    role: str,
) -> dict[str, Any]:
    # Legacy wrapper: keep existing call sites stable while v2 schema is now default.
    return evaluate_answer_runtime_v2(
        question=question,
        answer=answer,
        transcript=transcript,
        role=role,
    )


def _force_topic_closure(
    *,
    answer_class: str,
    answer_relevance: str,
    cross_topic_reuse: bool,
    last_question_type: str,
) -> tuple[bool, str | None]:
    if cross_topic_reuse:
        return True, "reused_answer"
    if (
        last_question_type in {"verification", "claim_verification", "deep_technical"}
        and answer_relevance == "low"
        and answer_class in {"generic", "evasive", "no_experience_honest", "partial"}
    ):
        return True, "low_relevance_after_probe"
    return False, None


def _is_topic_saturated(
    *,
    current_signal: str | None,
    answer_class: str,
    answer_relevance: str,
    topic_turns: int,
    last_question_type: str,
) -> tuple[bool, str | None]:
    if current_signal == "strong" and answer_relevance in {"medium", "high"}:
        return True, "topic_mastered"
    if (
        last_question_type in {"verification", "claim_verification", "deep_technical"}
        and answer_class in {"strong", "partial"}
        and answer_relevance == "high"
    ):
        return True, "topic_saturated"
    if topic_turns >= 1 and answer_class == "partial" and answer_relevance in {"medium", "high"}:
        return True, "enough_partial_signal"
    return False, None


def _build_diversification_hint(
    *,
    next_target: dict | None,
    current_target: dict | None,
    closed_reason: str | None,
    language: str,
) -> str | None:
    if not next_target:
        return None
    next_competencies = [str(item) for item in next_target.get("competencies", []) if item]
    next_label = next_competencies[0] if next_competencies else ""
    current_verification = str((current_target or {}).get("verification_target") or "").strip()
    next_verification = str(next_target.get("verification_target") or "").strip()

    parts: list[str] = []
    if language == "en":
        if next_label:
            parts.append(f"Shift the angle to {next_label}.")
        if current_verification:
            parts.append(f"Do not stay on {current_verification}.")
        if next_verification and next_verification != current_verification:
            parts.append(f"If relevant, ground the question in {next_verification}.")
        if closed_reason in {"topic_mastered", "topic_saturated", "enough_partial_signal"}:
            parts.append("Treat the previous topic as sufficiently covered and move to a different dimension.")
        elif closed_reason in {"reused_answer", "low_relevance_after_probe", "claim_unverified_after_probe"}:
            parts.append("Ask from a clearly different angle so the candidate cannot reuse the previous answer.")
    else:
        if next_label:
            parts.append(f"Смени угол и сфокусируйся на теме «{next_label}».")
        if current_verification:
            parts.append(f"Не продолжай спрашивать про {current_verification}.")
        if next_verification and next_verification != current_verification:
            parts.append(f"Если уместно, заземли вопрос в опыте с {next_verification}.")
        if closed_reason in {"topic_mastered", "topic_saturated", "enough_partial_signal"}:
            parts.append("Считай предыдущую тему достаточно раскрытой и переходи к другому измерению опыта.")
        elif closed_reason in {"reused_answer", "low_relevance_after_probe", "claim_unverified_after_probe"}:
            parts.append("Задай вопрос с явно другого угла, чтобы кандидат не мог повторить прежний ответ.")
    return " ".join(parts) if parts else None


def _topic_guard_decision(
    *,
    claim_target: str | None,
    verified_skills: set[str],
    probed_claim_targets: set[str],
    can_probe_current_topic: bool,
) -> tuple[bool, str | None]:
    """Return (must_probe_claim, closure_reason_if_advancing).

    Guard rule:
    - Stay on the current topic until its planned claim target is either
      verified, explicitly probed once, or explicitly closed by rule.
    """
    normalized_claim = str(claim_target or "").strip().lower()
    if not normalized_claim:
        return False, None

    normalized_verified = {str(item).strip().lower() for item in verified_skills}
    normalized_probed = {str(item).strip().lower() for item in probed_claim_targets}
    unresolved_claim = normalized_claim not in normalized_verified
    if not unresolved_claim:
        return False, None

    if can_probe_current_topic and normalized_claim not in normalized_probed:
        return True, None

    if not can_probe_current_topic:
        return False, "claim_unverified_after_probe"

    return False, None


def _rank_verification_target(
    *,
    current_claim_target: str | None,
    new_techs: set[str],
    current_question: str | None,
    verified_skills: set[str],
    probed_claim_targets: set[str],
) -> str | None:
    """Choose the most relevant technology to verify next.

    Priority:
    1. Current topic's planned claim target if it was actually mentioned or the question is about it
    2. Technologies explicitly mentioned in the current answer
    3. Current claim target as a fallback
    """
    question_lower = (current_question or "").lower()
    normalized_claim = (current_claim_target or "").lower().strip() or None

    if (
        normalized_claim
        and normalized_claim not in verified_skills
        and normalized_claim not in probed_claim_targets
        and (normalized_claim in new_techs or normalized_claim in question_lower)
    ):
        return normalized_claim

    candidates = [
        tech for tech in sorted(new_techs)
        if tech not in verified_skills and tech not in probed_claim_targets
    ]
    if candidates:
        return candidates[0]

    if (
        normalized_claim
        and normalized_claim not in verified_skills
        and normalized_claim not in probed_claim_targets
    ):
        return normalized_claim

    return None


def _topic_signature_key(topic: dict | None) -> str:
    data = topic or {}
    phase = str(data.get("phase") or "").strip().lower()
    block = str(data.get("block") or "").strip().lower()
    tier = str(data.get("tier") or "").strip().lower()
    verification_target = str(data.get("verification_target") or "").strip().lower()
    competencies = [str(item).strip().lower() for item in data.get("competencies", []) if item]
    primary_competency = competencies[0] if competencies else ""
    return "|".join([phase, block, tier, verification_target, primary_competency])


def _question_text_fingerprint(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) > 2 and token.lower() not in _QUESTION_STOPWORDS
    }


def _question_text_similarity(left: str, right: str) -> float:
    left_tokens = _question_text_fingerprint(left)
    right_tokens = _question_text_fingerprint(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _is_repeated_question_text(candidate: str, previous_questions: list[str], *, threshold: float = 0.66) -> bool:
    normalized_candidate = " ".join((candidate or "").strip().lower().split()).rstrip(" ?!.")
    if not normalized_candidate:
        return False
    for previous in previous_questions[-12:]:
        normalized_previous = " ".join((previous or "").strip().lower().split()).rstrip(" ?!.")
        if not normalized_previous:
            continue
        if normalized_candidate == normalized_previous:
            return True
        if _question_text_similarity(normalized_candidate, normalized_previous) >= threshold:
            return True
    return False


def _is_question_already_covered_in_transcript(
    question: str,
    transcript_summary: list[str],
    *,
    threshold: float = 0.58,
) -> bool:
    """Detect if a newly generated question overlaps with already covered summary themes."""
    normalized_question = " ".join((question or "").strip().lower().split()).rstrip(" ?!.")
    if not normalized_question:
        return False
    question_tokens = _question_text_fingerprint(normalized_question)
    if not question_tokens:
        return False
    for summary_item in transcript_summary[-12:]:
        normalized_summary = " ".join((summary_item or "").strip().lower().split()).rstrip(" ?!.")
        if not normalized_summary:
            continue
        summary_tokens = _question_text_fingerprint(normalized_summary)
        if not summary_tokens:
            continue
        overlap_tokens = question_tokens & summary_tokens
        if _question_text_similarity(normalized_question, normalized_summary) >= threshold:
            return True
        if len(overlap_tokens) >= 3 and (len(overlap_tokens) / max(1, len(question_tokens))) >= 0.38:
            return True
    return False


_GENERIC_QUESTION_PHRASES = (
    "разберите кейс",
    "расскажите подробнее",
    "какой был кейс",
)

_FORBIDDEN_GENERIC_QUESTION_PHRASES = (
    "разберите один другой кейс",
    "контекст, ваши действия и измеримый результат",
    "контекст ваши действия и измеримый результат",
    "давайте проще по одному кейсу",
)

_CONCRETE_CONTEXT_HINTS = (
    "представьте",
    "например",
    "допустим",
    "сценар",
    "пользователь",
    "клиент",
    "перевод",
    "платеж",
    "релиз",
    "деплой",
    "инцидент",
    "api",
    "endpoint",
    "response",
    "request",
    "for example",
    "scenario",
    "suppose",
    "user",
    "customer",
    "incident",
)


def _is_generic_question_text_without_context(question: str) -> bool:
    normalized = " ".join((question or "").strip().lower().split())
    if not normalized:
        return True
    if not any(phrase in normalized for phrase in _GENERIC_QUESTION_PHRASES):
        return False
    return not any(hint in normalized for hint in _CONCRETE_CONTEXT_HINTS)


def _is_forbidden_generic_question_text(question: str) -> bool:
    normalized = " ".join((question or "").strip().lower().split())
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _FORBIDDEN_GENERIC_QUESTION_PHRASES)


def _has_concrete_scenario_or_example(question: str) -> bool:
    normalized = " ".join((question or "").strip().lower().split())
    if not normalized:
        return False
    return any(hint in normalized for hint in _CONCRETE_CONTEXT_HINTS)


def _map_v2_action_to_legacy(action: str) -> tuple[str, bool]:
    normalized = str(action or "").strip().lower()
    if normalized in {
        "pressure_followup",
        "follow_up",
        "ask_resume_followup",
        "answer_meta_then_redirect",
        "resume_redirect",
    }:
        return "followup", False
    if normalized in {"clarify", "simplify"}:
        return "clarification", False
    if normalized == "start_scenario":
        return "main", True
    if normalized == "continue_scenario":
        return "main", True
    if normalized == "switch_topic":
        return "main", True
    if normalized == "close_interview":
        return "main", True
    return "main", True


def _pick_v2_forced_scenario_decision(
    *,
    role: str,
    language: str,
    scenario_chains: list[dict[str, Any]],
    asked_question_texts: list[str],
    current_competency: str,
    active_scenario_id: str | None,
    active_scenario_step: int,
) -> dict[str, Any]:
    chains = [chain for chain in scenario_chains if isinstance(chain, dict)]
    candidate_chains: list[dict[str, Any]] = []
    if active_scenario_id:
        for chain in chains:
            if str(chain.get("case_id") or chain.get("id") or "").strip() == active_scenario_id:
                candidate_chains.append(chain)
                break
    for chain in chains:
        if chain not in candidate_chains:
            candidate_chains.append(chain)

    for chain in candidate_chains:
        chain_id = str(chain.get("case_id") or chain.get("id") or "").strip() or None
        chain_competency = str(chain.get("competency") or current_competency).strip()
        chain_difficulty = max(1, min(5, _safe_int(chain.get("difficulty_tier"), 3)))
        questions = [str(item).strip() for item in chain.get("questions", []) if str(item).strip()]
        if not questions:
            continue
        start_idx = active_scenario_step if chain_id and chain_id == active_scenario_id else 0
        for idx in range(max(0, start_idx), len(questions)):
            question = _sanitize_chat_question(questions[idx], language=language)
            if not question:
                continue
            if _is_repeated_question_text(question, asked_question_texts):
                continue
            action = "continue_scenario" if chain_id and chain_id == active_scenario_id and idx > 0 else "start_scenario"
            question_type, will_advance = _map_v2_action_to_legacy(action)
            return {
                "action": action,
                "question_text": question,
                "reason": "v2_forced_start_scenario_guardrail",
                "target_competency": chain_competency,
                "difficulty": chain_difficulty,
                "question_type": question_type,
                "will_advance": will_advance,
                "selected_topic_index": None,
                "scenario_case_id": chain_id,
                "scenario_step_index": idx,
            }

    diversified = _role_diversified_reframe_question(
        role=role,
        competency=current_competency,
        language=language,
    )
    fallback_question = _sanitize_chat_question(diversified, language=language) or _runtime_followup_question_text(
        language=language,
        followup_type="clarify",
        role=role,
        topic={"competencies": [current_competency]} if current_competency else None,
    )
    return {
        "action": "simplify",
        "question_text": fallback_question,
        "reason": "v2_forced_start_scenario_fallback",
        "target_competency": current_competency,
        "difficulty": 2,
        "question_type": "clarification",
        "will_advance": False,
        "selected_topic_index": None,
    }


async def _select_next_question_decision_v2(
    *,
    role: str,
    language: str,
    resume_summary: str,
    role_competency_map: Any,
    interview_state_v2: dict[str, Any],
    last_question: str | None,
    last_answer: str,
    last_answer_evaluation: dict[str, Any],
    transcript_summary: list[str],
    asked_questions: list[str],
    available_scenarios: list[dict[str, Any]],
    policy_action: str = "",
    candidate_intent: str = "",
    missing_signal: str = "",
    pressure_goal: str = "",
    reasoning_hints: dict[str, Any] | None = None,
    model_preference: str | None = None,
) -> dict[str, Any]:
    _ = model_preference
    strategist_ctx = InterviewStrategistContext(
        role=role,
        language=language,
        resume_summary=resume_summary,
        role_competency_map=role_competency_map,
        interview_state_v2=interview_state_v2,
        last_question=last_question or "",
        last_answer=last_answer,
        last_answer_evaluation=last_answer_evaluation,
        transcript_summary=transcript_summary,
        asked_questions=asked_questions,
        available_scenarios=available_scenarios,
        conversational_interviewer_mode=bool(settings.CONVERSATIONAL_INTERVIEWER_MODE),
        policy_action=policy_action,
        candidate_intent=candidate_intent,
        missing_signal=missing_signal,
        pressure_goal=pressure_goal,
        reasoning_hints=dict(reasoning_hints or {}),
    )

    decision = await decide_next_interview_action(strategist_ctx)
    action = str(decision.action or "ask_new_topic").strip()
    question_text = _sanitize_chat_question(decision.question_text, language=language) or ""
    target_competency = str(decision.target_competency or "").strip()
    scenario_case_id = str(decision.scenario_id or "").strip() or None
    scenario_step_index = max(0, int(decision.scenario_step or 0))
    difficulty = max(1, min(5, int(decision.difficulty_tier or 3)))
    reason = str(decision.reason or "v2_strategist").strip() or "v2_strategist"
    expected_signal = str(decision.expected_signal or "").strip()
    question_type, will_advance = _map_v2_action_to_legacy(action)

    return {
        "action": action,
        "question_text": question_text,
        "reason": reason,
        "target_competency": target_competency,
        "difficulty": difficulty,
        "question_type": question_type,
        "will_advance": will_advance,
        "selected_topic_index": None,
        "scenario_case_id": scenario_case_id,
        "scenario_step_index": scenario_step_index,
        "expected_signal": expected_signal,
        "phase": str(decision.phase or "").strip().lower() or None,
        "strategist_raw_response": str(getattr(decision, "strategist_raw_response", "") or ""),
        "strategist_json_valid": bool(getattr(decision, "strategist_json_valid", False)),
        "strategist_repair_applied": bool(getattr(decision, "strategist_repair_applied", False)),
        "strategist_retry_used": bool(getattr(decision, "strategist_retry_used", False)),
        "strategist_error_reason": str(getattr(decision, "strategist_error_reason", "") or ""),
        "conversational_intent": str(getattr(decision, "conversational_intent", "") or "").strip().lower(),
        "information_target": str(getattr(decision, "information_target", "") or "").strip(),
        "ai_provider": str(getattr(decision, "ai_provider", "") or "").strip(),
        "requested_model": str(getattr(decision, "requested_model", "") or "").strip(),
        "actual_model_used": str(getattr(decision, "actual_model_used", "") or "").strip(),
        "provider_attempts": list(getattr(decision, "provider_attempts", []) or []),
        "provider_errors": list(getattr(decision, "provider_errors", []) or []),
        "openrouter_fallback_used": bool(getattr(decision, "openrouter_fallback_used", False)),
    }


def _apply_v2_question_guardrails(
    *,
    question_decision: dict[str, Any],
    role: str,
    language: str,
    asked_question_texts: list[str],
    transcript_summary: list[str],
    current_competency: str,
    scenario_chains: list[dict[str, Any]],
    state_v2_before: dict[str, Any] | None,
    active_qa_scenario_id: str | None,
    active_qa_scenario_step: int,
) -> dict[str, Any]:
    adjusted = dict(question_decision)
    action = str(adjusted.get("action") or "ask_new_topic").strip().lower()
    question_text = _sanitize_chat_question(str(adjusted.get("question_text") or ""), language=language) or ""
    _ = (
        role,
        scenario_chains,
        state_v2_before,
        active_qa_scenario_id,
        active_qa_scenario_step,
    )
    adjusted["generic_guardrail_triggered"] = False
    adjusted["forbidden_generic_guardrail_triggered"] = False
    adjusted["question_repeated_guardrail_triggered"] = False

    if _is_repeated_question_text(question_text, asked_question_texts):
        adjusted["repeated_increment"] = 1
        adjusted["question_repeated_guardrail_triggered"] = True
        adjusted["guardrail_reason"] = "repeated_question_rejected"

    if _is_forbidden_generic_question_text(question_text):
        adjusted["forbidden_generic_guardrail_triggered"] = True
        adjusted["generic_guardrail_triggered"] = True
        adjusted["guardrail_reason"] = "forbidden_generic_question_rejected"

    if _is_generic_question_text_without_context(question_text):
        adjusted["generic_guardrail_triggered"] = True
        adjusted["guardrail_reason"] = "generic_question_without_context_rejected"

    if action == "simplify" and not _has_concrete_scenario_or_example(question_text):
        adjusted["simplify_context_guardrail_triggered"] = True
        adjusted["generic_guardrail_triggered"] = True
        adjusted["guardrail_reason"] = "simplify_without_context_rejected"

    if (
        not adjusted.get("generic_guardrail_triggered")
        and not adjusted.get("forbidden_generic_guardrail_triggered")
        and not adjusted.get("question_repeated_guardrail_triggered")
        and _is_question_already_covered_in_transcript(question_text, transcript_summary)
    ):
        diversified = _role_diversified_reframe_question(
            role=role,
            competency=current_competency,
            language=language,
        )
        diversified = _sanitize_chat_question(diversified, language=language)
        if diversified and not _is_repeated_question_text(diversified, asked_question_texts):
            adjusted["question_text"] = diversified
            adjusted["reason"] = f"{str(adjusted.get('reason') or 'v2_strategist')}_transcript_diversified"

    return adjusted


def _role_diversified_reframe_question(
    *,
    role: str,
    competency: str,
    language: str,
) -> str:
    competency_key = competency.lower()
    if role == "qa_engineer":
        if "test strategy" in competency_key:
            return (
                "Разберём конкретный QA-кейс: новая фича оплаты. Какие 3 проверки вы берёте в smoke и почему?"
                if language != "en"
                else "Let's use a concrete QA case: new checkout feature. Which 3 checks go to smoke first, and why?"
            )
        if "test automation" in competency_key:
            return (
                "Возьмём один автотест из практики: что именно автоматизировали, какой риск закрыли и как проверили стабильность?"
                if language != "en"
                else "Take one real automation test: what exactly did you automate, what risk did it close, and how did you validate stability?"
            )
        if "api & performance" in competency_key:
            return (
                "Один API-кейс: какой endpoint тестировали, какие негативные сценарии и какой критерий успеха использовали?"
                if language != "en"
                else "One API case: which endpoint did you test, what negative scenarios did you include, and what success criterion did you use?"
            )
        if "root cause" in competency_key:
            return (
                "Один дефект из продакшна: шаги воспроизведения, где нашли первопричину и чем подтвердили фикс?"
                if language != "en"
                else "One production defect: reproduction steps, where root cause was found, and how the fix was validated?"
            )
    if role == "backend_engineer":
        return (
            "Окей, давайте на конкретном backend-кейсе: API вернул 500 под нагрузкой. Какие 2 первых проверки сделаете и почему?"
            if language != "en"
            else "Okay, take a concrete backend case: API returns 500 under load. What are your first 2 checks and why?"
        )
    if role == "frontend_engineer":
        return (
            "Окей, конкретный frontend-кейс: после релиза часть пользователей видит пустой экран. Что проверите первым?"
            if language != "en"
            else "Okay, concrete frontend case: after release some users see a blank screen. What do you check first?"
        )
    if role == "devops_engineer":
        return (
            "Окей, конкретный DevOps-кейс: pod ушёл в CrashLoopBackOff. Какие сигналы и где проверите сначала?"
            if language != "en"
            else "Okay, concrete DevOps case: a pod enters CrashLoopBackOff. Which signals and where do you check first?"
        )
    if role == "data_scientist":
        return (
            "Окей, конкретный DS-кейс: модель просела на проде. Какие 2 гипотезы проверите первыми?"
            if language != "en"
            else "Okay, concrete DS case: model quality dropped in production. Which 2 hypotheses do you test first?"
        )
    if role == "product_manager":
        return (
            "Окей, конкретный PM-кейс: после релиза просела ключевая метрика. Что проверите первым и почему?"
            if language != "en"
            else "Okay, concrete PM case: key metric dropped after release. What do you check first and why?"
        )
    if role in {"designer", "ux_ui_designer"}:
        return (
            "Окей, конкретный UX/UI-кейс: пользователи не завершают onboarding. Какие 2 проверки сделаете в первую очередь?"
            if language != "en"
            else "Okay, concrete UX/UI case: users do not complete onboarding. What are your first 2 checks?"
        )
    if role == "mobile_engineer":
        return (
            "Окей, конкретный mobile-кейс: crash только на части Android-устройств. Что проверите первым?"
            if language != "en"
            else "Okay, concrete mobile case: crash happens only on some Android devices. What do you check first?"
        )
    return (
        "Окей, давайте на одном конкретном рабочем примере: что произошло и что вы сделали первым шагом?"
        if language != "en"
        else "Okay, let's use one concrete work example: what happened and what was your first action?"
    )


_TOPIC_SIGNAL_WEIGHTS = {
    "strong": 1.0,
    "partial": 0.6,
    "generic": 0.25,
    "no_experience_honest": 0.2,
    "evasive": 0.0,
}


def _is_qa_technical_phase(topic: dict | None) -> bool:
    phase = str((topic or {}).get("phase") or "").strip().lower()
    return phase == "technical"


def _qa_chain_questions(chain: dict | None) -> list[str]:
    if not isinstance(chain, dict):
        return []
    return [str(item).strip() for item in chain.get("questions", []) if str(item).strip()]


def _qa_chain_by_id(chains: list[dict], case_id: str | None) -> dict | None:
    normalized_id = str(case_id or "").strip()
    if not normalized_id:
        return None
    for chain in chains:
        if str(chain.get("case_id") or "").strip() == normalized_id:
            return chain
    return None


def _qa_pick_next_chain(chains: list[dict], completed_case_ids: list[str]) -> dict | None:
    completed = {str(item).strip() for item in completed_case_ids if str(item).strip()}
    for chain in chains:
        chain_id = str(chain.get("case_id") or "").strip()
        if chain_id and chain_id not in completed:
            return chain
    return chains[0] if chains else None


def _qa_chain_followup_text(*, chain: dict, followup_type: str, fallback_text: str) -> str:
    followup_rules = chain.get("followup_rules") if isinstance(chain, dict) else None
    if isinstance(followup_rules, dict):
        candidate = str(followup_rules.get(followup_type) or "").strip()
        if candidate:
            return candidate
    return fallback_text


def _is_qa_case_block(topic: dict | None) -> bool:
    block = str((topic or {}).get("block") or "").strip().lower()
    return block in {"resume_followup", "technical_foundation", "technical_depth"}


def _qa_case_questions_asked_count(topic_plan: list[dict], asked_topics: list[str]) -> int:
    if not topic_plan:
        return 0
    asked_set = {str(item).strip() for item in asked_topics if str(item).strip()}
    total = 0
    for topic in topic_plan:
        if not _is_qa_case_block(topic):
            continue
        if _topic_signature_key(topic) in asked_set:
            total += 1
    return total


def _qa_technical_signal_percent(topic_plan: list[dict], topic_signals: list[str], asked_topics: list[str]) -> float:
    if not topic_plan:
        return 0.0
    asked_set = {str(item).strip() for item in asked_topics if str(item).strip()}
    scores: list[float] = []
    for idx, topic in enumerate(topic_plan):
        if not _is_qa_case_block(topic):
            continue
        if _topic_signature_key(topic) not in asked_set:
            continue
        signal = str(topic_signals[idx] if idx < len(topic_signals) else "").strip().lower()
        if not signal:
            continue
        scores.append(_TOPIC_SIGNAL_WEIGHTS.get(signal, 0.0))
    if not scores:
        return 0.0
    return round((sum(scores) / len(scores)) * 100.0, 1)


def _find_next_unasked_technical_topic_index(
    topic_plan: list[dict],
    *,
    asked_topics: list[str],
    topic_signals: list[str],
) -> int | None:
    if not topic_plan:
        return None
    asked_set = {str(item).strip() for item in asked_topics if str(item).strip()}
    candidates: list[tuple[float, int]] = []
    for idx, topic in enumerate(topic_plan):
        phase = str(topic.get("phase") or "").strip().lower()
        if phase in {"intro", "behavioral_closing"}:
            continue
        signature = _topic_signature_key(topic)
        if signature in asked_set:
            continue
        signal = str(topic_signals[idx] if idx < len(topic_signals) else "").strip().lower()
        score = _TOPIC_SIGNAL_WEIGHTS.get(signal, 0.0) if signal else -1.0
        candidates.append((score, idx))
    if not candidates:
        return None
    # Prefer slots that are still uncovered first, then lower-signal ones.
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def _find_next_unasked_case_topic_index(
    topic_plan: list[dict],
    *,
    asked_topics: list[str],
) -> int | None:
    if not topic_plan:
        return None
    asked_set = {str(item).strip() for item in asked_topics if str(item).strip()}
    for idx, topic in enumerate(topic_plan):
        if not _is_qa_case_block(topic):
            continue
        if _topic_signature_key(topic) in asked_set:
            continue
        return idx
    return None


def _topic_primary_competency(topic: dict | None) -> str:
    competencies = [str(item).strip() for item in (topic or {}).get("competencies", []) if str(item).strip()]
    return competencies[0] if competencies else ""


def _derive_covered_and_weak_topics(
    *,
    topic_plan: list[dict],
    topic_signals: list[str],
    asked_topics: list[str],
) -> tuple[list[str], list[str]]:
    if not topic_plan:
        return [], []
    asked_set = {str(item).strip() for item in asked_topics if str(item).strip()}
    covered: list[str] = []
    weak: list[str] = []
    for idx, topic in enumerate(topic_plan):
        signature = _topic_signature_key(topic)
        if not signature or signature not in asked_set:
            continue
        signal = str(topic_signals[idx] if idx < len(topic_signals) else "").strip().lower()
        if signal in {"strong", "partial"}:
            covered.append(signature)
        else:
            weak.append(signature)
    return covered, weak


def _runtime_followup_question_text(
    *,
    language: str,
    followup_type: str,
    role: str,
    topic: dict | None,
) -> str:
    competency = _topic_primary_competency(topic)
    if followup_type == "simplify":
        return (
            "Окей, давайте проще и на примере: какая была задача, что сделали лично вы и как подтвердили результат?"
            if language != "en"
            else "Let me rephrase simply: take one real example from your work. What was the task, what did you do personally, and what was the result?"
        )
    if followup_type == "deep_dive":
        return _role_diversified_reframe_question(role=role, competency=competency, language=language)
    if followup_type == "clarify":
        return build_pressure_followup(
            role=role,
            current_question="",
            candidate_answer="",
            competency=competency,
            scenario_context="",
            language=language,
            force_concrete_example=True,
        )
    return build_pressure_followup(
        role=role,
        current_question="",
        candidate_answer="",
        competency=competency,
        scenario_context="",
        language=language,
        force_concrete_example=True,
    )


def _build_interviewer_reply_then_question(
    *,
    language: str,
    intent: str,
    role: str,
    base_question: str,
    resume_context_hint: str | None = None,
) -> str:
    is_en = str(language).lower().startswith("en")
    question = _sanitize_chat_question(base_question, language=language) or base_question
    resume_hint = (resume_context_hint or "").strip()

    if intent == "meta_question":
        prefix = (
            "Могу, но сейчас важно понять ваш ход мысли как кандидата. Давайте проще: "
            if not is_en
            else "I can, but now it's important to understand your reasoning as a candidate. Let's make it simpler: "
        )
        return f"{prefix}{question}".strip()

    if intent == "request_personalized_to_resume":
        role_context = (
            "в вашем контексте сопровождения мобильного банка"
            if not is_en
            else "in your mobile banking support context"
        )
        if resume_hint:
            role_context = resume_hint[:90]
        prefix = (
            f"Ок, привяжем к вашему опыту ({role_context}). "
            if not is_en
            else f"Okay, let's tie it to your experience ({role_context}). "
        )
        return f"{prefix}{question}".strip()

    if intent in {"clarification_request", "confusion"}:
        prefix = (
            "Переформулирую проще. "
            if not is_en
            else "Let me rephrase more simply. "
        )
        return f"{prefix}{question}".strip()

    if intent == "refusal_or_no_knowledge":
        prefix = (
            "Ок, давайте через базовый сценарий. "
            if not is_en
            else "Okay, let's use a baseline scenario. "
        )
        return f"{prefix}{question}".strip()

    return question


def _select_next_topic_index_decision(
    *,
    topic_plan: list[dict],
    current_topic_index: int,
    covered_topics: list[str],
    weak_topics: list[str],
    asked_topics: list[str],
    role: str,
    max_questions: int,
) -> int:
    if not topic_plan:
        return 0
    covered_set = set(covered_topics)
    asked_set = {str(item).strip() for item in asked_topics if str(item).strip()}

    if role == "qa_engineer":
        asked_count = max(1, len(asked_set))
        case_count = _qa_case_questions_asked_count(topic_plan, asked_topics)
        case_ratio = case_count / asked_count
        if case_ratio < 0.6:
            qa_case_idx = _find_next_unasked_case_topic_index(topic_plan, asked_topics=asked_topics)
            if qa_case_idx is not None:
                return qa_case_idx

    for idx in range(max(current_topic_index + 1, 0), len(topic_plan)):
        topic = topic_plan[idx]
        signature = _topic_signature_key(topic)
        if not signature:
            continue
        if signature in covered_set:
            continue
        return idx

    fallback_idx = _find_next_unasked_technical_topic_index(
        topic_plan,
        asked_topics=asked_topics,
        topic_signals=[],
    )
    if fallback_idx is not None:
        return fallback_idx

    if weak_topics:
        weak_set = set(weak_topics)
        for idx, topic in enumerate(topic_plan):
            if _topic_signature_key(topic) in weak_set:
                return idx

    return min(max(current_topic_index + 1, 0), len(topic_plan) - 1)


def _select_next_question_decision(
    *,
    interview_state: dict[str, Any],
    last_answer_evaluation: dict[str, Any],
    covered_topics: list[str],
    weak_topics: list[str],
    role_question_banks: list[dict],
    scenario_chains: list[dict],
    topic_plan: list[dict],
    current_topic_index: int,
    asked_topics: list[str],
    asked_question_texts: list[str],
    role: str,
    language: str,
    current_question: str | None,
) -> dict[str, Any]:
    current_topic = topic_plan[current_topic_index] if 0 <= current_topic_index < len(topic_plan) else {}
    current_question_text = " ".join((current_question or "").strip().split())
    role_blocks_count = len(role_question_banks or [])
    quality = str(last_answer_evaluation.get("quality") or "no_signal")
    followup_type = str(last_answer_evaluation.get("followup_type") or "clarify")
    interviewer_failure = bool(last_answer_evaluation.get("interviewer_failure"))
    has_technical_detail = bool(last_answer_evaluation.get("has_technical_detail"))
    has_example = bool(last_answer_evaluation.get("has_example"))
    difficulty = int(interview_state.get("adaptive_difficulty_tier", 3) or 3)
    desired_followups = max(0, int(interview_state.get("topic_turns", 0) or 0))
    active_qa_scenario_id = str(interview_state.get("active_qa_scenario_id") or "").strip() or None
    active_qa_scenario_step = max(0, _safe_int(interview_state.get("active_qa_scenario_step"), 0))
    completed_qa_scenarios = [
        str(item).strip()
        for item in interview_state.get("qa_completed_scenarios", [])
        if str(item).strip()
    ]

    if role == "qa_engineer" and _is_qa_technical_phase(current_topic):
        chains = list(scenario_chains or [])
        active_chain = _qa_chain_by_id(chains, active_qa_scenario_id)
        if active_chain is None:
            active_chain = _qa_pick_next_chain(chains, completed_qa_scenarios)
            active_qa_scenario_step = 0
        if active_chain:
            chain_case_id = str(active_chain.get("case_id") or "").strip()
            chain_questions = _qa_chain_questions(active_chain)
            chain_title = str(active_chain.get("title") or "").strip()
            chain_competency = str(active_chain.get("competency") or _topic_primary_competency(current_topic)).strip()
            chain_difficulty = _safe_int(active_chain.get("difficulty_tier"), difficulty or 3)
            chain_difficulty = min(5, max(1, chain_difficulty))
            step_index = min(active_qa_scenario_step, max(len(chain_questions) - 1, 0))
            current_step_question = chain_questions[step_index] if chain_questions else ""
            completed_case_id = None

            if interviewer_failure:
                fallback = _runtime_followup_question_text(
                    language=language,
                    followup_type="simplify",
                    role=role,
                    topic=current_topic,
                )
                simplify_text = _qa_chain_followup_text(
                    chain=active_chain,
                    followup_type="simplify",
                    fallback_text=fallback,
                )
                contextual = f"Кейс: {chain_title}. {simplify_text}".strip()
                return {
                    "question_text": contextual,
                    "reason": "qa_chain_interviewer_failure_rephrase",
                    "target_competency": chain_competency,
                    "difficulty": max(1, chain_difficulty - 1),
                    "question_type": "clarification",
                    "will_advance": False,
                    "selected_topic_index": current_topic_index,
                    "scenario_case_id": chain_case_id,
                    "scenario_step_index": step_index,
                }

            if quality == "weak":
                fallback = _runtime_followup_question_text(
                    language=language,
                    followup_type=followup_type,
                    role=role,
                    topic=current_topic,
                )
                followup_text = _qa_chain_followup_text(
                    chain=active_chain,
                    followup_type="clarify",
                    fallback_text=fallback,
                )
                contextual = f"Кейс: {chain_title}. {followup_text}".strip()
                return {
                    "question_text": contextual,
                    "reason": "qa_chain_weak_answer_followup",
                    "target_competency": chain_competency,
                    "difficulty": max(1, chain_difficulty - 1),
                    "question_type": "followup",
                    "will_advance": False,
                    "selected_topic_index": current_topic_index,
                    "scenario_case_id": chain_case_id,
                    "scenario_step_index": step_index,
                }

            if quality == "medium":
                fallback = _runtime_followup_question_text(
                    language=language,
                    followup_type="deep_dive" if has_example and has_technical_detail else "clarify",
                    role=role,
                    topic=current_topic,
                )
                followup_text = _qa_chain_followup_text(
                    chain=active_chain,
                    followup_type="deep_dive",
                    fallback_text=fallback,
                )
                contextual = f"Кейс: {chain_title}. {followup_text}".strip()
                return {
                    "question_text": contextual,
                    "reason": "qa_chain_medium_answer_refine",
                    "target_competency": chain_competency,
                    "difficulty": chain_difficulty,
                    "question_type": "edge_cases",
                    "will_advance": False,
                    "selected_topic_index": current_topic_index,
                    "scenario_case_id": chain_case_id,
                    "scenario_step_index": step_index,
                }

            next_step_index = step_index + 1
            if next_step_index >= len(chain_questions):
                completed_case_id = chain_case_id
                updated_completed = list(completed_qa_scenarios)
                if chain_case_id and chain_case_id not in updated_completed:
                    updated_completed.append(chain_case_id)
                next_chain = _qa_pick_next_chain(chains, updated_completed)
                if next_chain and str(next_chain.get("case_id") or "").strip() != chain_case_id:
                    next_chain_id = str(next_chain.get("case_id") or "").strip()
                    next_chain_questions = _qa_chain_questions(next_chain)
                    if next_chain_questions:
                        next_text = next_chain_questions[0]
                        if _is_repeated_question_text(next_text, asked_question_texts):
                            next_text = f"Новый кейс: {str(next_chain.get('title') or '').strip()}. {next_text}"
                        return {
                            "question_text": next_text,
                            "reason": "qa_chain_switch_to_next_case",
                            "target_competency": str(next_chain.get("competency") or ""),
                            "difficulty": _safe_int(next_chain.get("difficulty_tier"), chain_difficulty),
                            "question_type": "main",
                            "will_advance": True,
                            "selected_topic_index": current_topic_index,
                            "scenario_case_id": next_chain_id,
                            "scenario_step_index": 0,
                            "completed_scenario_case_id": completed_case_id,
                        }
                return {
                    "question_text": "",
                    "reason": "qa_chain_case_completed_continue_flow",
                    "target_competency": chain_competency,
                    "difficulty": min(5, max(chain_difficulty, difficulty)),
                    "question_type": "main",
                    "will_advance": True,
                    "selected_topic_index": _select_next_topic_index_decision(
                        topic_plan=topic_plan,
                        current_topic_index=current_topic_index,
                        covered_topics=covered_topics,
                        weak_topics=weak_topics,
                        asked_topics=asked_topics,
                        role=role,
                        max_questions=int(interview_state.get("max_questions", len(topic_plan)) or len(topic_plan)),
                    ),
                    "scenario_case_id": chain_case_id,
                    "scenario_step_index": step_index,
                    "completed_scenario_case_id": completed_case_id,
                }
            else:
                next_question_text = chain_questions[next_step_index]
                if _is_repeated_question_text(next_question_text, asked_question_texts):
                    next_question_text = f"Уточним по кейсу «{chain_title}»: {next_question_text}"
                return {
                    "question_text": next_question_text,
                    "reason": "qa_chain_advance_step",
                    "target_competency": chain_competency,
                    "difficulty": min(5, max(chain_difficulty, difficulty)),
                    "question_type": "main",
                    "will_advance": True,
                    "selected_topic_index": current_topic_index,
                    "scenario_case_id": chain_case_id,
                    "scenario_step_index": next_step_index,
                    "completed_scenario_case_id": completed_case_id,
                }

    if interviewer_failure:
        return {
            "question_text": _runtime_followup_question_text(
                language=language,
                followup_type="simplify",
                role=role,
                topic=current_topic,
            ),
            "reason": "interviewer_failure_detected_rephrase",
            "target_competency": _topic_primary_competency(current_topic),
            "difficulty": max(1, difficulty - 1),
            "question_type": "clarification",
            "will_advance": False,
            "selected_topic_index": current_topic_index,
        }

    if quality == "weak":
        return {
            "question_text": _runtime_followup_question_text(
                language=language,
                followup_type=followup_type,
                role=role,
                topic=current_topic,
            ),
            "reason": "weak_answer_followup_required",
            "target_competency": _topic_primary_competency(current_topic),
            "difficulty": max(1, difficulty - 1),
            "question_type": "followup" if followup_type != "simplify" else "clarification",
            "will_advance": False,
            "selected_topic_index": current_topic_index,
        }

    if quality == "medium":
        question_type = "edge_cases" if has_example and has_technical_detail else "followup"
        return {
            "question_text": _runtime_followup_question_text(
                language=language,
                followup_type="deep_dive" if question_type == "edge_cases" else "clarify",
                role=role,
                topic=current_topic,
            ),
            "reason": "medium_answer_needs_refinement",
            "target_competency": _topic_primary_competency(current_topic),
            "difficulty": difficulty,
            "question_type": question_type,
            "will_advance": False,
            "selected_topic_index": current_topic_index,
        }

    if quality == "strong" and desired_followups < 1 and has_technical_detail and has_example:
        return {
            "question_text": "",
            "reason": "strong_answer_advance_topic",
            "target_competency": _topic_primary_competency(current_topic),
            "difficulty": min(5, difficulty + 1),
            "question_type": "main",
            "will_advance": True,
            "selected_topic_index": _select_next_topic_index_decision(
                topic_plan=topic_plan,
                current_topic_index=current_topic_index,
                covered_topics=covered_topics,
                weak_topics=weak_topics,
                asked_topics=asked_topics,
                role=role,
                max_questions=int(interview_state.get("max_questions", len(topic_plan)) or len(topic_plan)),
            ),
        }

    # default: strong/no_signal edge -> targeted deep dive on same topic
    return {
        "question_text": _runtime_followup_question_text(
            language=language,
            followup_type="deep_dive",
            role=role,
            topic=current_topic,
        ),
        "reason": "default_deep_dive_same_topic" if role_blocks_count > 0 or current_question_text else "default_deep_dive_without_bank",
        "target_competency": _topic_primary_competency(current_topic),
        "difficulty": difficulty,
        "question_type": "deep_technical",
        "will_advance": False,
        "selected_topic_index": current_topic_index,
    }


def _topic_signature(topic: dict | None) -> tuple[str, str]:
    data = topic or {}
    verification_target = str(data.get("verification_target") or "").strip().lower()
    competencies = [str(item).strip().lower() for item in data.get("competencies", []) if item]
    primary_competency = competencies[0] if competencies else ""
    return verification_target, primary_competency


def _validate_assessment_result(result: Any) -> AssessmentResult:
    if not isinstance(result, AssessmentResult):
        raise ValueError("Assessor returned invalid result type")
    if result.hiring_recommendation not in {"strong_yes", "yes", "maybe", "no"}:
        raise ValueError("Assessor returned invalid hiring recommendation")
    if not isinstance(result.full_report_json, dict):
        raise ValueError("Assessor returned invalid full_report_json payload")
    return result


def _apply_low_confidence_verdict_guard(result: AssessmentResult) -> AssessmentResult:
    """Map confidence bands to safe verdict policy for hiring recommendation."""
    confidence = float(result.overall_confidence or 0.0)
    if confidence < 0.40:
        confidence_verdict = "insufficient_data"
    elif confidence < 0.70:
        confidence_verdict = "needs_human_review"
    else:
        confidence_verdict = "normal"

    if confidence_verdict != "normal" and result.hiring_recommendation != "maybe":
        result.hiring_recommendation = "maybe"
    if isinstance(result.full_report_json, dict):
        reasons = list(result.full_report_json.get("recommendation_gate_reasons") or [])
        if confidence_verdict == "insufficient_data":
            reason = "overall confidence below 40%; signal is insufficient for a hard hire verdict"
        elif confidence_verdict == "needs_human_review":
            reason = "overall confidence below 70%; human review is required before hard hire verdict"
        else:
            reason = ""
        result.full_report_json["confidence_verdict"] = confidence_verdict
        overall_assessment = result.full_report_json.get("overall_assessment")
        if isinstance(overall_assessment, dict):
            overall_assessment["confidence_verdict"] = confidence_verdict
            overall_assessment["insufficient_signal"] = confidence_verdict != "normal"
        if reason not in reasons:
            if reason:
                reasons.append(reason)
        result.full_report_json["recommendation_gate_reasons"] = reasons
    return result


async def _get_next_question_with_dev_fallback(
    ctx: InterviewContext,
    model_preference: str | None = None,
) -> str:
    async def _call_with_optional_override(client: Any) -> str:
        if model_preference is None:
            return await client.get_next_question(ctx)
        try:
            return await client.get_next_question(ctx, model_override=model_preference)
        except TypeError:
            return await client.get_next_question(ctx)

    try:
        return await _call_with_optional_override(interviewer)
    except Exception as exc:
        record_ai_error(
            component="interviewer",
            provider="grok",
            model=str(model_preference or "runtime-default"),
            error=f"interviewer service call failed: {exc.__class__.__name__}",
        )
        if settings.is_local_or_test:
            logger.exception(
                "Interviewer generation failed in local/test mode; using deterministic fallback",
            )
            try:
                logger.warning(
                    "ai_fallback component=interviewer from_provider=grok to_provider=mock reason=local_or_test_failure",
                )
                question = await _call_with_optional_override(MockInterviewer())
                record_ai_success(
                    component="interviewer",
                    provider="mock",
                    model="mock-interviewer",
                    note="dev fallback activated",
                )
                return question
            except Exception:
                logger.exception("Deterministic interviewer fallback also failed")
        raise RuntimeError("AI interviewer request failed") from exc


async def _assess_with_dev_fallback(
    *,
    target_role: str,
    message_history: list[dict],
    message_timestamps: list[dict] | None,
    behavioral_signals: dict | None,
    language: str,
    interview_meta: dict | None,
) -> AssessmentResult:
    workspace_ai_settings = interview_meta.get("workspace_ai_settings") if isinstance(interview_meta, dict) else {}
    assessor_model_preference = None
    if isinstance(workspace_ai_settings, dict):
        assessor_model_preference = workspace_ai_settings.get("assessor_model_preference")
    try:
        result = await asyncio.wait_for(
            assessor.assess(
                target_role=target_role,
                message_history=message_history,
                message_timestamps=message_timestamps,
                behavioral_signals=behavioral_signals,
                language=language,
                interview_meta=interview_meta,
                model_override=assessor_model_preference,
            ),
            timeout=_assessment_timeout_seconds(),
        )
        return _validate_assessment_result(result)
    except Exception as exc:
        record_ai_error(
            component="assessor",
            provider="grok",
            model=str(assessor_model_preference or "runtime-default"),
            error=f"assessor service call failed: {exc.__class__.__name__}",
        )
        if settings.is_local_or_test:
            logger.exception(
                "Assessment generation failed in local/test mode; using deterministic fallback",
            )
            try:
                logger.warning(
                    "ai_fallback component=assessor from_provider=grok to_provider=mock reason=local_or_test_failure",
                )
                fallback_result = await MockAssessor().assess(
                    target_role=target_role,
                    message_history=message_history,
                    message_timestamps=message_timestamps,
                    behavioral_signals=behavioral_signals,
                    language=language,
                    interview_meta=interview_meta,
                    model_override=assessor_model_preference,
                )
                record_ai_success(
                    component="assessor",
                    provider="mock",
                    model="mock-assessor",
                    note="dev fallback activated",
                )
                return _validate_assessment_result(fallback_result)
            except Exception:
                logger.exception("Deterministic assessor fallback also failed")
        raise RuntimeError("AI assessor request failed") from exc


def _resolve_next_topic_index(
    *,
    topic_plan: list[dict],
    current_topic_index: int,
    default_next_index: int,
    close_reason: str | None,
) -> int:
    if not topic_plan:
        return default_next_index
    if default_next_index >= len(topic_plan):
        return default_next_index

    next_index = max(0, default_next_index)
    if close_reason not in {"reused_answer", "low_relevance_after_probe", "claim_unverified_after_probe"}:
        return next_index

    current_sig = _topic_signature(
        topic_plan[current_topic_index] if 0 <= current_topic_index < len(topic_plan) else {}
    )

    cursor = next_index
    while cursor < len(topic_plan):
        if _topic_signature(topic_plan[cursor]) != current_sig:
            return cursor
        cursor += 1

    return next_index


def _is_structured_phase_plan(topic_plan: list[dict]) -> bool:
    if not topic_plan:
        return False
    for item in topic_plan:
        if not isinstance(item, dict):
            continue
        if str(item.get("phase") or "").strip():
            return True
    return False


def _behavioral_phase_index(topic_plan: list[dict]) -> int:
    if not topic_plan:
        return 0
    for idx, item in enumerate(topic_plan):
        if not isinstance(item, dict):
            continue
        if str(item.get("phase") or "").strip().lower() == "behavioral_closing":
            return idx
    return max(len(topic_plan) - 1, 0)


def _role_core_coverage_requirements(
    *,
    role: str,
    topic_plan: list[dict],
    required_competencies_count: int = 3,
) -> tuple[int, list[str]]:
    """Return (highest_required_slot_index, missing_competencies_in_plan).

    highest_required_slot_index is 0-based and indicates the latest slot we must reach
    before allowing aggressive early-stop/reduction.
    """
    if not topic_plan:
        return 0, []

    ordered = [item for item in get_role_core_competency_order(role) if item]
    required = ordered[: max(1, required_competencies_count)]
    if not required:
        return 0, []

    competency_to_slot: dict[str, int] = {}
    for idx, item in enumerate(topic_plan):
        if not isinstance(item, dict):
            continue
        competencies = item.get("competencies")
        if not isinstance(competencies, list) or not competencies:
            continue
        primary = str(competencies[0]).strip()
        if primary and primary not in competency_to_slot:
            competency_to_slot[primary] = idx

    present_slots = [competency_to_slot[name] for name in required if name in competency_to_slot]
    missing = [name for name in required if name not in competency_to_slot]
    highest_required_slot = max(present_slots) if present_slots else 0
    return highest_required_slot, missing


def _rebuild_topic_plan_with_max_questions(
    *,
    topic_plan: list[dict],
    target_role: str,
    resume_profile: dict | None,
    max_questions: int,
) -> list[dict]:
    if not topic_plan:
        return []
    structured_flow = _is_structured_phase_plan(topic_plan)
    return build_interview_plan(
        target_role,
        max(1, max_questions),
        resume_profile or {},
        structured_flow=structured_flow,
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def start_interview(
    db: AsyncSession,
    candidate: Candidate,
    target_role: str,
    template_id: uuid.UUID | None = None,
    language: str = "ru",
    seniority_level: str | None = None,
    module_type: str | None = None,
    module_title: str | None = None,
    module_config: dict[str, Any] | None = None,
    workspace_ai_settings: dict[str, Any] | None = None,
) -> StartInterviewResponse:
    # Guard: active resume required
    active_resume = await db.scalar(
        select(Resume).where(
            Resume.candidate_id == candidate.id,
            Resume.is_active.is_(True),
        )
    )
    if not active_resume:
        raise NoActiveResumeError()

    # Optionally load template
    template: InterviewTemplate | None = None
    if template_id:
        template = await db.scalar(
            select(InterviewTemplate).where(InterviewTemplate.id == template_id)
        )

    normalized_module_type = str(module_type or "").strip().lower() or None
    normalized_module_title = str(module_title or "").strip() or None
    safe_module_config = module_config if isinstance(module_config, dict) else {}
    safe_workspace_ai_settings = await build_effective_workspace_ai_settings(
        db,
        workspace_ai_settings if isinstance(workspace_ai_settings, dict) else {},
    )
    normalized_seniority_level = _normalize_interview_seniority(seniority_level)

    resume_profile = preprocess_resume(active_resume.raw_text, target_role)
    if normalized_seniority_level:
        resume_profile["seniority_hint"] = normalized_seniority_level
    module_context: dict[str, Any] | None = None
    if normalized_module_type == _SYSTEM_DESIGN_MODULE_TYPE:
        topic_plan, module_context = _build_system_design_topic_plan(
            target_role=target_role,
            language=language,
            module_config=safe_module_config,
        )
        max_q = len(topic_plan)
        role_max_cap = max_q
        min_questions_before_early_stop = max_q
    elif normalized_module_type == _BEHAVIORAL_INTERVIEW_MODULE_TYPE:
        topic_plan, module_context = _build_behavioral_interview_topic_plan(
            target_role=target_role,
            language=language,
            module_config=safe_module_config,
        )
        max_q = len(topic_plan)
        role_max_cap = max_q
        min_questions_before_early_stop = max_q
    elif normalized_module_type == _CODING_TASK_MODULE_TYPE:
        topic_plan, module_context = _build_coding_task_topic_plan(
            target_role=target_role,
            language=language,
            module_config=safe_module_config,
        )
        max_q = len(topic_plan)
        role_max_cap = max_q
        min_questions_before_early_stop = max_q
    elif normalized_module_type == _SQL_LIVE_MODULE_TYPE:
        topic_plan, module_context = _build_sql_live_topic_plan(
            target_role=target_role,
            language=language,
            module_config=safe_module_config,
        )
        max_q = len(topic_plan)
        role_max_cap = max_q
        min_questions_before_early_stop = max_q
    elif normalized_module_type == _WRITTEN_COMMUNICATION_MODULE_TYPE:
        topic_plan, module_context = _build_written_communication_topic_plan(
            target_role=target_role,
            language=language,
            module_config=safe_module_config,
        )
        max_q = len(topic_plan)
        role_max_cap = max_q
        min_questions_before_early_stop = max_q
    else:
        adaptive_max_q, adaptive_role_cap, adaptive_min_questions = _estimate_dynamic_question_budget(
            target_role=target_role,
            resume_profile=resume_profile,
            selected_seniority=normalized_seniority_level,
        )
        if template:
            template_budget = len(template.questions)
            role_max_cap = max(adaptive_role_cap, template_budget)
            max_q = min(role_max_cap, max(adaptive_max_q, template_budget))
            min_questions_before_early_stop = max(
                adaptive_min_questions,
                min(template_budget, max_q),
            )
        else:
            max_q = adaptive_max_q
            role_max_cap = adaptive_role_cap
            min_questions_before_early_stop = adaptive_min_questions
        topic_plan = build_interview_plan(
            target_role,
            max_q,
            resume_profile,
            structured_flow=template is None,
        )

    # Create interview — store resume_id snapshot at start time
    interview = Interview(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        resume_id=active_resume.id,
        template_id=template_id,
        status="created",
        target_role=target_role,
        seniority_level=normalized_seniority_level,
        question_count=0,
        max_questions=max_q,
        language=language,
        started_at=datetime.utcnow(),
    )
    db.add(interview)
    await db.flush()  # get interview.id

    # Store competency plan as system message for persistence
    import json
    plan_content = json.dumps(
        {
            "topic_plan": topic_plan,
            "resume_profile": resume_profile,
            "module_context": module_context,
        },
        ensure_ascii=False,
    )
    db.add(InterviewMessage(
        id=uuid.uuid4(),
        interview_id=interview.id,
        role="system",
        content=plan_content,
    ))

    # Generate and persist first question (always via LLM, template is guidance)
    resume_context_for_interviewer = (
        str(resume_profile.get("interview_resume_context") or "").strip()
        or active_resume.raw_text
    )

    ctx = InterviewContext(
        target_role=target_role,
        seniority_level=normalized_seniority_level,
        difficulty_tier=3,
        question_number=1,
        max_questions=max_q,
        message_history=[],
        resume_text=resume_context_for_interviewer,
        template_questions=template.questions if template else None,
        competency_targets=topic_plan[0]["competencies"] if topic_plan else None,
        language=language,
        resume_anchor=topic_plan[0].get("resume_anchor") if topic_plan else None,
        verification_target=topic_plan[0].get("verification_target") if topic_plan else None,
        topic_phase=topic_plan[0].get("phase") if topic_plan else None,
        question_block=topic_plan[0].get("block") if topic_plan else None,
        question_tier=topic_plan[0].get("tier") if topic_plan else None,
        lead_question=topic_plan[0].get("lead_question") if topic_plan else None,
        allowed_probes=list(topic_plan[0].get("allowed_probes") or []) if topic_plan else [],
        scored_metrics=list(topic_plan[0].get("scored_metrics") or []) if topic_plan else [],
        candidate_memory=[],
        current_topic=_topic_signature_key(topic_plan[0] if topic_plan else {}),
        asked_topics=[],
        transcript_summary=[],
        module_type=normalized_module_type,
        module_title=normalized_module_title,
        module_scenario_id=topic_plan[0].get("scenario_id") if topic_plan else None,
        module_scenario_title=topic_plan[0].get("scenario_title") if topic_plan else None,
        module_scenario_prompt=topic_plan[0].get("scenario_prompt") if topic_plan else None,
        module_stage_key=topic_plan[0].get("stage_key") if topic_plan else None,
        module_stage_title=topic_plan[0].get("stage_title") if topic_plan else None,
        module_stage_prompt=topic_plan[0].get("stage_prompt") if topic_plan else None,
        module_stage_index=0,
        module_stage_count=len(module_context.get("stage_plan", [])) if module_context else 0,
    )
    interviewer_model_preference = safe_workspace_ai_settings.get("interviewer_model_preference")
    first_question = await _get_next_question_with_dev_fallback(
        ctx,
        model_preference=interviewer_model_preference,
    )
    first_question = _sanitize_chat_question(first_question, language=language) or first_question

    db.add(InterviewMessage(
        id=uuid.uuid4(),
        interview_id=interview.id,
        role="assistant",
        content=first_question,
    ))

    # question_count tracks core interview questions only
    interview.question_count = 1
    initial_asked_topics: list[str] = []
    initial_asked_question_texts: list[str] = []
    if topic_plan:
        first_signature = _topic_signature_key(topic_plan[0])
        if first_signature:
            initial_asked_topics.append(first_signature)
    if first_question:
        initial_asked_question_texts.append(first_question)
    initial_state = {
        "turn_count": 1,
        "question_count": 1,
        "current_topic_index": 0,
        "topic_turns": 0,
        "clarification_turns": 0,
        "resume_profile": resume_profile,
        "topic_plan": topic_plan,
        "topic_signals": [],
        "answer_classes": [],
        "mentioned_technologies": [],
        "verified_skills": [],
        "probed_claim_targets": [],
        "contradiction_flags": [],
        "pending_verification": None,
        "last_question_type": "main",
        "previous_candidate_answers": [],
        "topic_reuse_flags": [],
        "topic_relevance_failures": [],
        "topic_closed_reasons": [],
        "topic_mastered_flags": [],
        "candidate_memory": [],
        "asked_topics": initial_asked_topics,
        "asked_question_texts": initial_asked_question_texts[-30:],
        "transcript_summary": [],
        "qa_scenario_progress": {},
        "active_qa_scenario_id": None,
        "active_qa_scenario_step": 0,
        "qa_completed_scenarios": [],
        "candidate_answers_count": 0,
        "strong_answers_count": 0,
        "weak_answers_count": 0,
        "consecutive_strong_answers": 0,
        "low_relevance_answers_count": 0,
        "consecutive_weak_answers": 0,
        "nonsense_answers_count": 0,
        "adaptive_difficulty_tier": 3,
        "adaptive_min_questions": min_questions_before_early_stop,
        "adaptive_role_max_cap": role_max_cap,
        "adaptive_last_decision": None,
        "seniority_level": normalized_seniority_level,
    }
    if safe_workspace_ai_settings:
        initial_state["workspace_ai_settings"] = {
            "proctoring_policy_mode": safe_workspace_ai_settings.get("proctoring_policy_mode"),
            "interviewer_model_preference": safe_workspace_ai_settings.get("interviewer_model_preference"),
            "assessor_model_preference": safe_workspace_ai_settings.get("assessor_model_preference"),
        }
    if normalized_module_type:
        initial_state.update(
            {
                "module_type": normalized_module_type,
                "module_title": normalized_module_title or _module_title_fallback(normalized_module_type),
                "module_config": safe_module_config,
                "module_scenario_id": (module_context or {}).get("scenario_id"),
                "module_scenario_title": (module_context or {}).get("scenario_title"),
                "module_scenario_prompt": (module_context or {}).get("scenario_prompt"),
                "module_stack_focus": (module_context or {}).get("stack_focus"),
                "module_preferred_language": (module_context or {}).get("preferred_language"),
                "module_workspace_hint": (module_context or {}).get("workspace_hint"),
                "module_stage_plan": list((module_context or {}).get("stage_plan") or []),
                "module_stage_index": 0,
                "module_question_history": list((module_context or {}).get("question_history") or []),
            }
        )
    if _is_interview_engine_v2_enabled(role=target_role):
        initial_state[_INTERVIEW_STATE_V2_KEY] = get_interview_state_v2(interview)
    interview.interview_state = initial_state
    interview.status = "in_progress"
    await db.commit()
    await db.refresh(interview)

    return StartInterviewResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        core_question_count=interview.question_count,
        asked_questions_count=1,
        answered_questions_count=0,
        current_question=first_question,
        language=interview.language,
        seniority_level=interview.seniority_level,
        interview_stage=_build_interview_stage_payload(interview),
    )


async def add_candidate_message(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
    message: str,
) -> SendMessageResponse:
    interview = await _get_interview(db, interview_id, candidate.id)

    if interview.status != "in_progress":
        if interview.status in ("report_generated", "completed"):
            raise InterviewAlreadyFinishedError()
        raise InterviewNotActiveError()

    # Guard: all questions answered and last message was from candidate → must finish
    messages = await _get_messages(db, interview.id)
    if (
        interview.question_count >= interview.max_questions
        and messages
        and messages[-1].role == "candidate"
    ):
        raise MaxQuestionsReachedError()

    # Persist candidate answer
    db.add(InterviewMessage(
        id=uuid.uuid4(),
        interview_id=interview.id,
        role="candidate",
        content=message,
    ))

    # Generate next question if quota not exhausted
    current_question: str | None = None
    question_type = "main"
    will_advance = True
    response_is_followup = False
    if interview.question_count < interview.max_questions:
        history = _to_history(messages)
        history.append({"role": "candidate", "content": message})

        # Load template questions if this interview uses a template
        template_questions: list[str] | None = None
        if interview.template_id:
            template = await db.scalar(
                select(InterviewTemplate).where(InterviewTemplate.id == interview.template_id)
            )
            template_questions = template.questions if template else None

        # Load persisted interview plan from system message
        topic_plan: list[dict] = []
        resume_profile: dict = {}
        module_context: dict[str, Any] = {}
        for msg in messages:
            if msg.role == "system":
                try:
                    plan_data = json.loads(msg.content)
                    topic_plan = plan_data.get("topic_plan", [])
                    resume_profile = plan_data.get("resume_profile", {})
                    raw_module_context = plan_data.get("module_context")
                    module_context = raw_module_context if isinstance(raw_module_context, dict) else {}
                    break
                except (json.JSONDecodeError, KeyError):
                    pass

        resume = await db.scalar(select(Resume).where(Resume.id == interview.resume_id))

        # ── Load persistent interview state ────────────────────────────────
        state: dict = interview.interview_state or {}
        engine_v2_enabled = _is_interview_engine_v2_enabled(role=interview.target_role)
        state_v2_before = get_interview_state_v2(interview) if engine_v2_enabled else None
        coding_task_artifact = _get_coding_task_artifact_state(state)
        written_artifact = _get_written_artifact_state(state)
        turn_count: int = int(state.get("turn_count", interview.question_count))
        current_topic_index: int = int(state.get("current_topic_index", max(interview.question_count - 1, 0)))
        topic_turns: int = int(state.get("topic_turns", interview.followup_depth or 0))
        topic_signals: list[str] = list(state.get("topic_signals", []))
        answer_classes: list[str] = list(state.get("answer_classes", []))
        mentioned_technologies: set[str] = set(state.get("mentioned_technologies", []))
        verified_skills: set[str] = set(state.get("verified_skills", []))
        probed_claim_targets: set[str] = set(state.get("probed_claim_targets", []))
        contradiction_flags: list[str] = list(state.get("contradiction_flags", []))
        pending_verification: str | None = state.get("pending_verification")
        previous_candidate_answers: list[dict] | list[str] = list(state.get("previous_candidate_answers", []))
        topic_reuse_flags: list[bool] = list(state.get("topic_reuse_flags", []))
        topic_relevance_failures: list[int] = list(state.get("topic_relevance_failures", []))
        topic_closed_reasons: list[str] = list(state.get("topic_closed_reasons", []))
        topic_mastered_flags: list[bool] = list(state.get("topic_mastered_flags", []))
        clarification_turns = _safe_int(state.get("clarification_turns"), 0)
        last_question_type: str = str(state.get("last_question_type", "main"))
        candidate_memory: list[str] = list(state.get("candidate_memory", []))
        asked_topics: list[str] = [str(item).strip() for item in state.get("asked_topics", []) if str(item).strip()]
        asked_question_texts: list[str] = [
            str(item).strip()
            for item in state.get("asked_question_texts", [])
            if str(item).strip()
        ]
        transcript_summary: list[str] = [str(item).strip() for item in state.get("transcript_summary", []) if str(item).strip()]
        runtime_answer_evaluations: list[dict[str, Any]] = list(state.get("runtime_answer_evaluations", []))
        question_decision_history: list[dict[str, Any]] = list(state.get("question_decision_history", []))
        qa_scenario_progress = (
            dict(state.get("qa_scenario_progress"))
            if isinstance(state.get("qa_scenario_progress"), dict)
            else {}
        )
        active_qa_scenario_id = str(state.get("active_qa_scenario_id") or "").strip() or None
        active_qa_scenario_step = _safe_int(state.get("active_qa_scenario_step"), 0)
        qa_completed_scenarios = [
            str(item).strip()
            for item in state.get("qa_completed_scenarios", [])
            if str(item).strip()
        ]
        pressure_followup_last_key = str(state.get("pressure_followup_last_key") or "").strip()
        resume_evidence = _normalize_resume_evidence(
            (state_v2_before or {}).get("resume_evidence") if isinstance(state_v2_before, dict) else None
        )
        resume_evidence_before = dict(resume_evidence)
        decision_traces_v2: list[dict[str, Any]] = (
            list((state_v2_before or {}).get("decision_traces", []))
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else []
        )
        interview_quality_metrics_before = (
            _normalize_interview_quality_metrics((state_v2_before or {}).get("interview_quality_metrics"))
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else _default_interview_quality_metrics()
        )
        conversational_intent_history: list[str] = (
            [
                str(item).strip().lower()
                for item in (state_v2_before or {}).get("conversational_intent_history", [])
                if str(item).strip()
            ]
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else []
        )
        information_target_history: list[str] = (
            [
                str(item).strip()
                for item in (state_v2_before or {}).get("information_target_history", [])
                if str(item).strip()
            ]
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else []
        )
        semantic_repeated_question_count_before = (
            max(0, _safe_int((state_v2_before or {}).get("semantic_repeated_question_count"), 0))
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else 0
        )
        weak_answer_streak_v2 = _safe_int((state_v2_before or {}).get("weak_answer_streak"), 0) if engine_v2_enabled else 0
        no_case_streak_v2 = _safe_int((state_v2_before or {}).get("no_case_streak"), 0) if engine_v2_enabled else 0
        resume_scored_turns_before = (
            _safe_int((state_v2_before or {}).get("resume_scored_turns"), 0)
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else 0
        )
        resume_scored_turns_after = resume_scored_turns_before
        last_step_key_v2 = str((state_v2_before or {}).get("last_step_key") or "") if engine_v2_enabled else ""
        current_phase_before_v2 = (
            str((state_v2_before or {}).get("phase") or "intro")
            if engine_v2_enabled and isinstance(state_v2_before, dict)
            else None
        )
        module_type = str(state.get("module_type") or module_context.get("module_type") or "").strip().lower() or None
        module_title = str(state.get("module_title") or "").strip() or None
        module_stage_plan = list(
            state.get("module_stage_plan")
            if isinstance(state.get("module_stage_plan"), list)
            else module_context.get("stage_plan", [])
        )
        module_stage_index = _safe_int(state.get("module_stage_index"), current_topic_index)
        module_question_history = list(
            state.get("module_question_history")
            if isinstance(state.get("module_question_history"), list)
            else module_context.get("question_history", [])
        )
        module_scenario_id = str(state.get("module_scenario_id") or module_context.get("scenario_id") or "").strip() or None
        module_scenario_title = str(state.get("module_scenario_title") or module_context.get("scenario_title") or "").strip() or None
        module_scenario_prompt = str(state.get("module_scenario_prompt") or module_context.get("scenario_prompt") or "").strip() or None
        module_stack_focus = str(state.get("module_stack_focus") or module_context.get("stack_focus") or "").strip() or None
        module_preferred_language = str(state.get("module_preferred_language") or module_context.get("preferred_language") or "").strip() or None
        module_workspace_hint = str(state.get("module_workspace_hint") or module_context.get("workspace_hint") or "").strip() or None
        if _is_staged_module_type(module_type) and topic_plan:
            current_topic_index = min(max(module_stage_index, 0), len(topic_plan) - 1)
        candidate_answers_count = _safe_int(state.get("candidate_answers_count"), 0)
        strong_answers_count = _safe_int(state.get("strong_answers_count"), 0)
        weak_answers_count = _safe_int(state.get("weak_answers_count"), 0)
        consecutive_strong_answers = _safe_int(state.get("consecutive_strong_answers"), 0)
        low_relevance_answers_count = _safe_int(state.get("low_relevance_answers_count"), 0)
        consecutive_weak_answers = _safe_int(state.get("consecutive_weak_answers"), 0)
        nonsense_answers_count = _safe_int(state.get("nonsense_answers_count"), 0)
        adaptive_difficulty_tier = _safe_int(state.get("adaptive_difficulty_tier"), 3)
        min_questions_before_early_stop = _safe_int(
            state.get("adaptive_min_questions"),
            min(_ADAPTIVE_MIN_QUESTIONS_FLOOR, interview.max_questions),
        )
        role_max_cap = _safe_int(
            state.get("adaptive_role_max_cap"),
            _ROLE_MAX_QUESTION_CAP.get(interview.target_role, interview.max_questions),
        )

        # ── Analyse current answer ──────────────────────────────────────────
        answer_class, shallow_reason = classify_answer(message)
        last_answer_words = len(message.strip().split())
        new_techs = extract_mentioned_technologies(message)
        mentioned_technologies.update(new_techs)
        # Techs mentioned but not yet verified
        unverified_techs = new_techs - verified_skills

        current_target = topic_plan[current_topic_index] if current_topic_index < len(topic_plan) else {}
        current_topic_phase = str(current_target.get("phase") or "").strip().lower()
        claim_target = current_target.get("verification_target")
        current_question_text = next(
            (msg.content for msg in reversed(messages) if msg.role == "assistant"),
            None,
        )
        runtime_status = get_ai_runtime_status() if engine_v2_enabled else {}
        trace: dict[str, Any] | None = None
        if engine_v2_enabled:
            trace = {
                "at": datetime.utcnow().isoformat() + "Z",
                "engine_version": "v2",
                "provider": str(runtime_status.get("provider") or "unknown"),
                "model": str(runtime_status.get("model") or "unknown"),
                "ai_provider": str(runtime_status.get("provider") or "unknown"),
                "requested_model": None,
                "actual_model_used": None,
                "provider_attempts": [],
                "provider_errors": [],
                "openrouter_fallback_used": False,
                "current_phase_before": current_phase_before_v2,
                "current_phase_after": None,
                "candidate_intent": None,
                "intent_reason": None,
                "should_count_as_answer": None,
                "answer_evaluation": None,
                "policy_action": None,
                "policy_reason": None,
                "resume_evidence_before": resume_evidence_before,
                "resume_evidence_after": None,
                "resume_gate_passed": _resume_deep_dive_gate_opened(resume_evidence_before),
                "conversational_intent": None,
                "information_target": None,
                "semantic_repeat_streak": 0,
                "semantic_repeat_detected": False,
                "selected_generator": None,
                "generated_question_before_guardrails": None,
                "generated_question_after_guardrails": None,
                "was_question_rejected_as_generic": False,
                "was_question_rejected_as_repeated": False,
                "scenario_id": active_qa_scenario_id,
                "scenario_step_before": active_qa_scenario_step,
                "scenario_step_after": None,
                "why_phase_advanced": None,
                "legacy_v1_override_applied": False,
                "legacy_v1_generated_question": None,
                "strategist_raw_response": "",
                "strategist_json_valid": None,
                "strategist_repair_applied": None,
                "strategist_retry_used": None,
                "strategist_error_reason": "",
            }
        intent_context = {
            "role": interview.target_role,
            "phase": (state_v2_before or {}).get("phase") if isinstance(state_v2_before, dict) else None,
            "current_question": current_question_text or "",
            "transcript_summary": transcript_summary[-10:],
            "resume_summary": str(resume_profile.get("interview_resume_context") or "").strip(),
        }
        candidate_intent = classify_candidate_intent(message, intent_context) if engine_v2_enabled else classify_candidate_intent_v2(message)
        candidate_intent_type = str(candidate_intent.get("intent") or "answer")
        should_count_as_answer = bool(candidate_intent.get("should_count_as_answer", True))
        should_advance_scenario = bool(candidate_intent.get("should_advance_scenario", True))
        if trace is not None:
            trace["candidate_intent"] = candidate_intent_type
            trace["intent_reason"] = str(candidate_intent.get("reason") or "")
            trace["should_count_as_answer"] = should_count_as_answer
            trace["resume_scored_turns_before"] = resume_scored_turns_before
        if should_count_as_answer:
            if engine_v2_enabled and current_phase_before_v2 in {"intro", "resume_deep_dive"}:
                resume_scored_turns_after += 1
            runtime_answer_evaluation = evaluate_answer_runtime_v2(
                question=current_question_text,
                answer=message,
                transcript=transcript_summary,
                role=interview.target_role,
            )
        else:
            runtime_answer_evaluation = {
                "quality": "no_signal",
                "evidence_type": "none",
                "has_concrete_example": False,
                "has_personal_action": False,
                "has_technical_detail": False,
                "has_result": False,
                "candidate_confusion": candidate_intent_type in {"clarification_request", "request_example", "meta_question", "challenge_interviewer"},
                "candidate_asks_clarification": candidate_intent_type in {"clarification_request", "request_example"},
                "answer_score": 0.0,
                "recommended_next_action": "simplify",
                "has_example": False,
                "depth_score": 0.0,
                "needs_followup": True,
                "followup_type": "simplify",
                "interviewer_failure": False,
                "pressure_followup_required": False,
            }
        runtime_answer_evaluation["candidate_intent"] = candidate_intent
        runtime_answer_evaluation["should_count_as_answer"] = should_count_as_answer
        runtime_answer_evaluation["should_advance_scenario"] = should_advance_scenario
        candidate_no_case_signal_now = (
            candidate_intent_type == "request_example"
            or (
                should_count_as_answer
                and not bool(runtime_answer_evaluation.get("has_concrete_example", runtime_answer_evaluation.get("has_example")))
            )
        )
        projected_no_case_streak_v2 = (no_case_streak_v2 + 1) if candidate_no_case_signal_now else 0
        if trace is not None:
            trace["answer_evaluation"] = _compact_answer_evaluation_for_trace(runtime_answer_evaluation)
        is_clarification_request = candidate_intent_type in {"clarification_request", "confusion"}
        is_move_on_request = _is_move_on_request(message)
        answer_relevance = _answer_relevance(
            question=current_question_text,
            answer=message,
            new_techs=new_techs,
            current_claim_target=claim_target,
        )
        is_nonsense_answer = _is_noise_or_nonsense_answer(message)
        cross_topic_reuse = _is_cross_topic_reuse(message, previous_candidate_answers, current_topic_index)
        current_step_key = f"{active_qa_scenario_id or '-'}:{max(0, active_qa_scenario_step)}:{max(0, current_topic_index)}"
        policy_decision = {
            "policy_action": "continue",
            "count_as_scored_answer": should_count_as_answer,
            "advance_phase": True,
            "advance_scenario": should_advance_scenario,
            "update_confusion_count": False,
            "update_weak_answer_count": False,
            "reason": "legacy_v1_path",
        }
        if engine_v2_enabled:
            policy_state = {
                "weak_answer_streak": _safe_int((state_v2_before or {}).get("weak_answer_streak"), 0),
                "last_step_key": str((state_v2_before or {}).get("last_step_key") or ""),
                "current_step_key": current_step_key,
            }
            policy_decision = decide_interview_policy(
                policy_state,
                candidate_intent,
                runtime_answer_evaluation,
            )
            should_count_as_answer = bool(policy_decision.get("count_as_scored_answer", should_count_as_answer))
            should_advance_scenario = bool(policy_decision.get("advance_scenario", should_advance_scenario))
            runtime_answer_evaluation["should_count_as_answer"] = should_count_as_answer
            runtime_answer_evaluation["should_advance_scenario"] = should_advance_scenario
            if trace is not None:
                trace["policy_action"] = str(policy_decision.get("policy_action") or "")
                trace["policy_reason"] = str(policy_decision.get("reason") or "")

        while len(topic_reuse_flags) <= current_topic_index:
            topic_reuse_flags.append(False)
        while len(topic_relevance_failures) <= current_topic_index:
            topic_relevance_failures.append(0)
        while len(topic_closed_reasons) <= current_topic_index:
            topic_closed_reasons.append("")
        while len(topic_mastered_flags) <= current_topic_index:
            topic_mastered_flags.append(False)

        if is_move_on_request:
            answer_class = "partial"
            shallow_reason = "candidate_requested_move_on"
            answer_relevance = "medium"
            is_nonsense_answer = False
            cross_topic_reuse = False
        elif candidate_intent_type in {"clarification_request", "request_example", "confusion"}:
            answer_class = "generic"
            shallow_reason = "clarification_request"
            answer_relevance = "low"
            is_nonsense_answer = False
            cross_topic_reuse = False
        elif candidate_intent_type in {"meta_question", "challenge_interviewer"}:
            answer_class = "generic"
            shallow_reason = "meta_question"
            answer_relevance = "low"
            is_nonsense_answer = False
            cross_topic_reuse = False
        elif candidate_intent_type == "request_resume_focus":
            answer_class = "generic"
            shallow_reason = "request_resume_focus"
            answer_relevance = "low"
            is_nonsense_answer = False
            cross_topic_reuse = False
        elif candidate_intent_type == "dont_know":
            answer_class = "no_experience_honest"
            shallow_reason = "dont_know"
            answer_relevance = "low"
            is_nonsense_answer = False
            cross_topic_reuse = False
        elif cross_topic_reuse and answer_relevance == "low":
            topic_reuse_flags[current_topic_index] = True
            answer_class = "evasive"
            shallow_reason = "reused_answer"
            answer_relevance = "low"
        elif cross_topic_reuse and answer_relevance in {"medium", "high"}:
            topic_reuse_flags[current_topic_index] = True
            if answer_class == "strong":
                answer_class = "partial"
            shallow_reason = "reused_but_relevant"
        elif answer_class in {"strong", "partial"} and answer_relevance == "low":
            # Keep descriptive answers as "partial" on main questions, otherwise
            # we over-trigger follow-ups and can stall legacy fixed-length interviews.
            if last_answer_words < 18 or last_question_type in {"verification", "claim_verification", "deep_technical"}:
                answer_class = "generic"
                shallow_reason = "low_relevance"
        elif answer_class == "strong" and answer_relevance == "medium":
            answer_class = "partial"
        if is_nonsense_answer:
            answer_class = "evasive"
            shallow_reason = "nonsense_input"
            answer_relevance = "low"
        if answer_relevance == "low":
            topic_relevance_failures[current_topic_index] += 1

        answer_classes.append(answer_class)
        if engine_v2_enabled:
            resume_topic_phase_for_evidence = current_topic_phase
            if (
                current_phase_before_v2 in {"intro", "resume_deep_dive"}
                and not _resume_deep_dive_gate_opened(resume_evidence_before)
            ):
                resume_topic_phase_for_evidence = "resume_followup"
            resume_evidence = _update_resume_evidence(
                resume_evidence=resume_evidence,
                answer=message,
                answer_evaluation=runtime_answer_evaluation,
                topic_phase=resume_topic_phase_for_evidence,
            )
        runtime_answer_evaluations.append(
            {
                "question_number": interview.question_count,
                "topic_index": current_topic_index,
                "question_type": last_question_type,
                "scenario_case_id": active_qa_scenario_id,
                "scenario_step_index": active_qa_scenario_step if active_qa_scenario_id else None,
                "intent": candidate_intent_type,
                "scored": should_count_as_answer,
                "evaluation": runtime_answer_evaluation,
                "policy_decision": policy_decision if engine_v2_enabled else None,
            }
        )

        # ── Session memory + adaptive quality counters ─────────────────────
        if should_count_as_answer:
            candidate_memory = _append_candidate_memory(
                candidate_memory,
                answer=message,
                answer_class=answer_class,
                answer_relevance=answer_relevance,
                new_techs=new_techs,
            )
            candidate_answers_count += 1

            is_strong_signal = answer_class == "strong" and answer_relevance in {"medium", "high"}
            is_weak_signal = answer_class in {"generic", "evasive", "no_experience_honest"} or answer_relevance == "low"

            if is_strong_signal:
                strong_answers_count += 1
                consecutive_strong_answers += 1
            else:
                consecutive_strong_answers = 0
            if is_weak_signal:
                weak_answers_count += 1
                consecutive_weak_answers += 1
            else:
                consecutive_weak_answers = 0
            if answer_relevance == "low":
                low_relevance_answers_count += 1
            if is_nonsense_answer:
                nonsense_answers_count += 1
            adaptive_difficulty_tier = _derive_adaptive_difficulty_tier(
                current_tier=adaptive_difficulty_tier,
                answer_class=answer_class,
                answer_relevance=answer_relevance,
                strong_answers_count=strong_answers_count,
                weak_answers_count=weak_answers_count,
                consecutive_strong_answers=consecutive_strong_answers,
                consecutive_weak_answers=consecutive_weak_answers,
            )
        transcript_summary = _append_transcript_summary(
            transcript_summary,
            topic=current_target,
            answer=message,
            answer_class=answer_class,
            answer_relevance=answer_relevance,
            is_clarification_request=is_clarification_request,
        )
        covered_topics, weak_topics = _derive_covered_and_weak_topics(
            topic_plan=topic_plan,
            topic_signals=topic_signals,
            asked_topics=asked_topics,
        )

        decision_input_state = {
            "adaptive_difficulty_tier": adaptive_difficulty_tier,
            "topic_turns": topic_turns,
            "max_questions": interview.max_questions,
            "active_qa_scenario_id": active_qa_scenario_id,
            "active_qa_scenario_step": active_qa_scenario_step,
            "qa_completed_scenarios": qa_completed_scenarios,
            "qa_scenario_progress": qa_scenario_progress,
        }
        role_scenario_chains = get_role_scenario_chains(interview.target_role)
        workspace_ai_settings = state.get("workspace_ai_settings")
        strategist_model_preference = None
        if isinstance(workspace_ai_settings, dict):
            strategist_model_preference = workspace_ai_settings.get("interviewer_model_preference")
        role_competency_map = get_role_core_competency_order(interview.target_role)
        resume_summary_for_strategy = str(resume_profile.get("interview_resume_context") or "").strip()
        current_competency_for_guard = ""
        competencies_for_guard = current_target.get("competencies") if isinstance(current_target, dict) else None
        if isinstance(competencies_for_guard, list) and competencies_for_guard:
            current_competency_for_guard = str(competencies_for_guard[0] or "").strip()
        if engine_v2_enabled:
            resume_gate_passed_for_strategy = _resume_deep_dive_gate_opened(resume_evidence)
            resume_force_transition_for_strategy = _resume_deep_dive_force_transition(
                resume_scored_turns=resume_scored_turns_after,
            )
            strategy_policy_action = str(policy_decision.get("policy_action") or "continue").strip().lower()
            if (
                str(current_phase_before_v2 or "") in {"intro", "resume_deep_dive"}
                and not resume_gate_passed_for_strategy
                and not resume_force_transition_for_strategy
            ):
                strategy_policy_action = "ask_resume_followup"
            elif resume_force_transition_for_strategy and str(current_phase_before_v2 or "") in {
                "intro",
                "resume_deep_dive",
            }:
                strategy_policy_action = "switch_topic"
            elif strategy_policy_action == "give_example_scenario":
                strategy_policy_action = "clarify"

            role_hint_competency = _topic_primary_competency(current_target) or current_competency_for_guard
            pressure_hint = build_pressure_followup(
                role=interview.target_role,
                current_question=current_question_text or "",
                candidate_answer=message,
                competency=role_hint_competency,
                scenario_context=str(active_qa_scenario_id or ""),
                language=interview.language,
                answer_evaluation=runtime_answer_evaluation,
            )
            concrete_example_hint = build_pressure_followup(
                role=interview.target_role,
                current_question=current_question_text or "",
                candidate_answer=message,
                competency=role_hint_competency,
                scenario_context=str(active_qa_scenario_id or ""),
                language=interview.language,
                answer_evaluation=runtime_answer_evaluation,
                force_concrete_example=True,
            )
            resume_followup_hint = _build_resume_deep_dive_followup(
                language=interview.language,
                resume_evidence=resume_evidence,
                resume_context=resume_summary_for_strategy,
            )
            raw_question_decision = await _select_next_question_decision_v2(
                role=interview.target_role,
                language=interview.language,
                resume_summary=resume_summary_for_strategy,
                role_competency_map=role_competency_map,
                interview_state_v2=state_v2_before or get_interview_state_v2(interview),
                last_question=current_question_text,
                last_answer=message,
                last_answer_evaluation=runtime_answer_evaluation,
                transcript_summary=transcript_summary,
                asked_questions=asked_question_texts,
                available_scenarios=role_scenario_chains,
                policy_action=strategy_policy_action,
                candidate_intent=candidate_intent_type,
                missing_signal=role_hint_competency,
                pressure_goal="collect_concrete_example_personal_action_result",
                reasoning_hints={
                    "resume_gate_passed": resume_gate_passed_for_strategy,
                    "resume_force_transition": resume_force_transition_for_strategy,
                    "resume_followup_hint": resume_followup_hint,
                    "pressure_followup_hint": pressure_hint,
                    "concrete_example_hint": concrete_example_hint,
                    "policy_reason": str(policy_decision.get("reason") or ""),
                    "intent_reason": str(candidate_intent.get("reason") or ""),
                },
                model_preference=strategist_model_preference,
            )
            if trace is not None:
                trace["selected_generator"] = "strategist"
                trace["generated_question_before_guardrails"] = str(raw_question_decision.get("question_text") or "").strip() or None
                trace["strategist_raw_response"] = str(raw_question_decision.get("strategist_raw_response") or "")
                trace["strategist_json_valid"] = bool(raw_question_decision.get("strategist_json_valid"))
                trace["strategist_repair_applied"] = bool(raw_question_decision.get("strategist_repair_applied"))
                trace["strategist_retry_used"] = bool(raw_question_decision.get("strategist_retry_used"))
                trace["strategist_error_reason"] = str(raw_question_decision.get("strategist_error_reason") or "")
                trace["ai_provider"] = str(raw_question_decision.get("ai_provider") or "")
                trace["requested_model"] = str(raw_question_decision.get("requested_model") or "")
                trace["actual_model_used"] = str(raw_question_decision.get("actual_model_used") or "")
                trace["provider_attempts"] = list(raw_question_decision.get("provider_attempts") or [])
                trace["provider_errors"] = list(raw_question_decision.get("provider_errors") or [])
                trace["openrouter_fallback_used"] = bool(raw_question_decision.get("openrouter_fallback_used"))

            raw_action = str(raw_question_decision.get("action") or "").strip().lower()
            inferred_intent = _derive_conversational_intent(
                raw_intent=str(raw_question_decision.get("conversational_intent") or ""),
                action=raw_action,
                phase=str((state_v2_before or {}).get("phase") or ""),
            )
            inferred_information_target = str(
                raw_question_decision.get("information_target")
                or raw_question_decision.get("target_competency")
                or current_competency_for_guard
                or ""
            ).strip()
            semantic_streak = _conversational_intent_streak(conversational_intent_history, inferred_intent)
            semantic_repeat_detected = semantic_streak >= 3 and bool(inferred_intent)
            raw_question_decision["conversational_intent"] = inferred_intent
            raw_question_decision["information_target"] = inferred_information_target

            if semantic_repeat_detected:
                adapted_question, adapted_intent, adapted_target = _semantic_anti_loop_adaptation(
                    role=interview.target_role,
                    language=interview.language,
                    current_question=current_question_text or "",
                    candidate_answer=message,
                    competency=current_competency_for_guard,
                    scenario_context=str(active_qa_scenario_id or ""),
                    resume_evidence=resume_evidence,
                    answer_evaluation=runtime_answer_evaluation,
                )
                raw_question_decision["question_text"] = adapted_question
                raw_question_decision["action"] = "clarify"
                raw_question_decision["question_type"] = "clarification"
                raw_question_decision["will_advance"] = False
                raw_question_decision["reason"] = (
                    f"{str(raw_question_decision.get('reason') or 'v2_strategist')}"
                    "_semantic_anti_loop_adaptation"
                )
                raw_question_decision["repeated_increment"] = max(
                    1,
                    _safe_int(raw_question_decision.get("repeated_increment"), 0),
                )
                raw_question_decision["conversational_intent"] = adapted_intent
                raw_question_decision["information_target"] = adapted_target
                if trace is not None:
                    trace["selected_generator"] = "strategist"
                    trace["generated_question_before_guardrails"] = str(adapted_question or "").strip() or None

            if trace is not None:
                trace["conversational_intent"] = str(raw_question_decision.get("conversational_intent") or "")
                trace["information_target"] = str(raw_question_decision.get("information_target") or "")
                trace["semantic_repeat_streak"] = semantic_streak
                trace["semantic_repeat_detected"] = semantic_repeat_detected
            question_decision = _apply_v2_question_guardrails(
                question_decision=raw_question_decision,
                role=interview.target_role,
                language=interview.language,
                asked_question_texts=asked_question_texts,
                transcript_summary=transcript_summary,
                current_competency=current_competency_for_guard,
                scenario_chains=role_scenario_chains,
                state_v2_before=state_v2_before,
                active_qa_scenario_id=active_qa_scenario_id,
                active_qa_scenario_step=active_qa_scenario_step,
            )
            if trace is not None:
                trace["generated_question_after_guardrails"] = str(question_decision.get("question_text") or "").strip() or None
                trace["was_question_rejected_as_generic"] = bool(
                    question_decision.get("generic_guardrail_triggered")
                    or question_decision.get("forbidden_generic_guardrail_triggered")
                    or question_decision.get("simplify_context_guardrail_triggered")
                )
                trace["was_question_rejected_as_repeated"] = bool(
                    question_decision.get("question_repeated_guardrail_triggered")
                )
                trace["ai_provider"] = str(question_decision.get("ai_provider") or trace.get("ai_provider") or "")
                trace["requested_model"] = str(question_decision.get("requested_model") or trace.get("requested_model") or "")
                trace["actual_model_used"] = str(question_decision.get("actual_model_used") or trace.get("actual_model_used") or "")
                trace["provider_attempts"] = list(question_decision.get("provider_attempts") or trace.get("provider_attempts") or [])
                trace["provider_errors"] = list(question_decision.get("provider_errors") or trace.get("provider_errors") or [])
                trace["openrouter_fallback_used"] = bool(
                    question_decision.get("openrouter_fallback_used")
                    if "openrouter_fallback_used" in question_decision
                    else trace.get("openrouter_fallback_used")
                )
                if trace["was_question_rejected_as_generic"] or trace["was_question_rejected_as_repeated"]:
                    trace["selected_generator"] = "interviewer_redirect"
        else:
            question_decision = _select_next_question_decision(
                interview_state=decision_input_state,
                last_answer_evaluation=runtime_answer_evaluation,
                covered_topics=covered_topics,
                weak_topics=weak_topics,
                role_question_banks=get_role_question_blocks(interview.target_role),
                scenario_chains=role_scenario_chains,
                topic_plan=topic_plan,
                current_topic_index=current_topic_index,
                asked_topics=asked_topics,
                asked_question_texts=asked_question_texts,
                role=interview.target_role,
                language=interview.language,
                current_question=current_question_text,
            )

        if is_clarification_request:
            should_end_now = False
            adaptive_decision = None
            adapted_max_questions = interview.max_questions
        elif _is_staged_module_type(module_type):
            should_end_now = False
            adaptive_decision = None
            adapted_max_questions = interview.max_questions
        else:
            role_max_cap = max(interview.max_questions, role_max_cap)
            adapted_max_questions, should_end_now, adaptive_decision = _adapt_question_budget(
                current_max_questions=interview.max_questions,
                current_question_count=interview.question_count,
                answer_count=candidate_answers_count,
                strong_answers_count=strong_answers_count,
                weak_answers_count=weak_answers_count,
                low_relevance_answers_count=low_relevance_answers_count,
                consecutive_weak_answers=consecutive_weak_answers,
                min_questions_before_early_stop=max(1, min_questions_before_early_stop),
                role_max_cap=role_max_cap,
                nonsense_answers_count=nonsense_answers_count,
            )
            interview.max_questions = adapted_max_questions
            if topic_plan and adapted_max_questions != len(topic_plan):
                topic_plan = _rebuild_topic_plan_with_max_questions(
                    topic_plan=topic_plan,
                    target_role=interview.target_role,
                    resume_profile=resume_profile,
                    max_questions=adapted_max_questions,
                )
                current_topic_index = min(max(current_topic_index, 0), max(len(topic_plan) - 1, 0))

            role_required_slot_idx, role_missing_competencies = _role_core_coverage_requirements(
                role=interview.target_role,
                topic_plan=topic_plan,
                required_competencies_count=3,
            )

            if should_end_now and current_topic_index < role_required_slot_idx:
                should_end_now = False
                adaptive_decision = "deferred_until_role_core"
                min_required_questions = max(interview.question_count + 1, role_required_slot_idx + 1)
                if adapted_max_questions < min_required_questions:
                    adapted_max_questions = min_required_questions
                    interview.max_questions = adapted_max_questions
                    if topic_plan and adapted_max_questions != len(topic_plan):
                        topic_plan = _rebuild_topic_plan_with_max_questions(
                            topic_plan=topic_plan,
                            target_role=interview.target_role,
                            resume_profile=resume_profile,
                            max_questions=adapted_max_questions,
                        )
                        current_topic_index = min(max(current_topic_index, 0), max(len(topic_plan) - 1, 0))

            # Keep question plan long enough to cover role-core technical sequence.
            if role_missing_competencies:
                logger.warning(
                    "Role core competencies missing in topic plan for role=%s: %s",
                    interview.target_role,
                    ", ".join(role_missing_competencies),
                )
            else:
                role_min_questions = max(role_required_slot_idx + 1, 1)
                if adapted_max_questions < role_min_questions:
                    adapted_max_questions = role_min_questions
                    interview.max_questions = adapted_max_questions
                    if topic_plan and adapted_max_questions != len(topic_plan):
                        topic_plan = _rebuild_topic_plan_with_max_questions(
                            topic_plan=topic_plan,
                            target_role=interview.target_role,
                            resume_profile=resume_profile,
                            max_questions=adapted_max_questions,
                        )
                        current_topic_index = min(max(current_topic_index, 0), max(len(topic_plan) - 1, 0))

            if _is_structured_phase_plan(topic_plan):
                behavioral_idx = _behavioral_phase_index(topic_plan)
                if should_end_now and current_topic_index < behavioral_idx:
                    should_end_now = False
                    adaptive_decision = "deferred_until_behavioral"
                    min_required_questions = max(interview.question_count + 1, behavioral_idx + 1)
                    if adapted_max_questions < min_required_questions:
                        adapted_max_questions = min_required_questions
                        interview.max_questions = adapted_max_questions
                        if topic_plan and adapted_max_questions != len(topic_plan):
                            topic_plan = _rebuild_topic_plan_with_max_questions(
                                topic_plan=topic_plan,
                                target_role=interview.target_role,
                                resume_profile=resume_profile,
                                max_questions=adapted_max_questions,
                            )
                            current_topic_index = min(max(current_topic_index, 0), max(len(topic_plan) - 1, 0))

            # ── Contradiction detection ─────────────────────────────────────
            # If we asked a verification question and got a shallow answer → flag it
            if pending_verification and answer_class in {"generic", "evasive", "no_experience_honest"}:
                contradiction_flags.append(f"possible exaggeration: {pending_verification}")
                pending_verification = None
            elif pending_verification and answer_class in {"strong", "partial"} and answer_relevance != "low":
                verified_skills.add(pending_verification)
                pending_verification = None

        # ── Question type state machine ─────────────────────────────────────
        # One core topic can have at most one extra probing turn.
        current_target = topic_plan[current_topic_index] if current_topic_index < len(topic_plan) else {}
        current_topic_phase = str(current_target.get("phase") or "").strip().lower()
        claim_target = current_target.get("verification_target")
        question_type = "main"
        next_pending_verification: str | None = None
        will_advance = True
        force_topic_closure, forced_closure_reason = _force_topic_closure(
            answer_class=answer_class,
            answer_relevance=answer_relevance,
            cross_topic_reuse=cross_topic_reuse,
            last_question_type=last_question_type,
        )
        current_signal = topic_signals[current_topic_index] if current_topic_index < len(topic_signals) else ""
        topic_saturated, saturation_reason = _is_topic_saturated(
            current_signal=current_signal,
            answer_class=answer_class,
            answer_relevance=answer_relevance,
            topic_turns=topic_turns,
            last_question_type=last_question_type,
        )

        can_probe_current_topic = topic_turns < 1 and interview.question_count < interview.max_questions
        force_structured_reframe = (
            consecutive_weak_answers >= 2
            and last_question_type == "main"
            and can_probe_current_topic
            and answer_class in {"generic", "evasive"}
        )
        topic_guard_closure_reason: str | None = None

        if is_move_on_request:
            question_type = "main"
            will_advance = True
            next_pending_verification = None
            forced_closure_reason = "candidate_requested_move_on"
            saturation_reason = None
        elif is_clarification_request:
            next_pending_verification = pending_verification
            if clarification_turns < 1:
                question_type = "clarification"
                will_advance = False
                forced_closure_reason = None
                saturation_reason = None
            else:
                question_type = "main"
                will_advance = True
                forced_closure_reason = "clarification_limit_reached"
                saturation_reason = None
        elif _is_staged_module_type(module_type):
            if last_question_type != "main":
                question_type = "main"
                will_advance = True
            elif answer_class == "no_experience_honest":
                if can_probe_current_topic and last_question_type == "main":
                    question_type = "followup"
                    will_advance = False
                else:
                    question_type = "main"
                    will_advance = True
                    forced_closure_reason = forced_closure_reason or f"{module_type}_honest_gap_acknowledged"
            elif force_structured_reframe:
                question_type = "structured_reframe"
                will_advance = False
            elif answer_class in {"generic", "evasive"} or answer_relevance == "low":
                if can_probe_current_topic:
                    question_type = "followup"
                    will_advance = False
                else:
                    question_type = "main"
                    will_advance = True
                    forced_closure_reason = forced_closure_reason or f"{module_type}_followup_spent"
            elif answer_class == "strong" and can_probe_current_topic:
                question_type = "deep_technical"
                will_advance = False
            else:
                question_type = "main"
                will_advance = True
        elif current_topic_phase == "intro":
            question_type = "main"
            will_advance = True
            next_pending_verification = None
            forced_closure_reason = forced_closure_reason or "intro_completed"
            saturation_reason = None
        elif current_topic_phase == "behavioral_closing":
            if last_question_type != "main":
                question_type = "main"
                will_advance = True
            elif answer_class == "no_experience_honest":
                if can_probe_current_topic and last_question_type == "main":
                    question_type = "followup"
                    will_advance = False
                else:
                    question_type = "main"
                    will_advance = True
                    forced_closure_reason = forced_closure_reason or "behavioral_honest_gap_acknowledged"
            elif force_structured_reframe:
                question_type = "structured_reframe"
                will_advance = False
            elif answer_class in {"generic", "evasive"} and can_probe_current_topic:
                question_type = "followup"
                will_advance = False
            else:
                question_type = "main"
                will_advance = True
                next_pending_verification = None
        else:
            can_probe_claim = (
                bool(claim_target)
                and claim_target not in probed_claim_targets
                and claim_target not in verified_skills
                and can_probe_current_topic
            )
            topic_guard_requires_probe, topic_guard_closure_reason = _topic_guard_decision(
                claim_target=claim_target,
                verified_skills=verified_skills,
                probed_claim_targets=probed_claim_targets,
                can_probe_current_topic=can_probe_current_topic,
            )

            ranked_claim_target = _rank_verification_target(
                current_claim_target=claim_target,
                new_techs=new_techs,
                current_question=current_question_text,
                verified_skills=verified_skills,
                probed_claim_targets=probed_claim_targets,
            )

            if should_end_now:
                question_type = "main"
                will_advance = True
                next_pending_verification = None
                forced_closure_reason = adaptive_decision or "early_stop_low_signal"
                saturation_reason = None
            elif force_topic_closure:
                question_type = "main"
                will_advance = True
            elif topic_saturated:
                question_type = "main"
                will_advance = True
            elif answer_class == "no_experience_honest":
                if can_probe_current_topic and last_question_type == "main":
                    question_type = "followup"
                    will_advance = False
                else:
                    question_type = "main"
                    will_advance = True
                    forced_closure_reason = forced_closure_reason or "honest_gap_acknowledged"
                next_pending_verification = None
            elif topic_guard_requires_probe:
                normalized_claim_target = str(claim_target or "").strip().lower()
                question_type = "claim_verification"
                next_pending_verification = normalized_claim_target
                probed_claim_targets.add(normalized_claim_target)
                will_advance = False

            elif can_probe_claim and ranked_claim_target and answer_class in {"generic", "evasive"}:
                question_type = "claim_verification"
                next_pending_verification = ranked_claim_target
                probed_claim_targets.add(ranked_claim_target)
                will_advance = False

            elif force_structured_reframe:
                question_type = "structured_reframe"
                will_advance = False

            elif answer_class in {"generic", "evasive"} and can_probe_current_topic:
                question_type = "followup"
                will_advance = False

            elif can_probe_current_topic and answer_class in {"strong", "partial"}:
                tech_to_verify = _rank_verification_target(
                    current_claim_target=claim_target,
                    new_techs=unverified_techs,
                    current_question=current_question_text,
                    verified_skills=verified_skills,
                    probed_claim_targets=probed_claim_targets,
                )
                if tech_to_verify:
                    question_type = "verification"
                    next_pending_verification = tech_to_verify
                    probed_claim_targets.add(tech_to_verify)
                    will_advance = False
                elif answer_class == "strong":
                    question_type = "deep_technical"
                    will_advance = False

            elif answer_class == "strong" and can_probe_current_topic:
                question_type = "deep_technical"
                will_advance = False

            else:
                question_type = "main"
                will_advance = True
                if topic_guard_closure_reason:
                    forced_closure_reason = forced_closure_reason or topic_guard_closure_reason

        # Decision-based selector overrides linear topic flow decisions.
        question_type = str(question_decision.get("question_type") or question_type)
        will_advance = bool(question_decision.get("will_advance", will_advance))
        selected_topic_index_preference = question_decision.get("selected_topic_index")
        if not isinstance(selected_topic_index_preference, int):
            selected_topic_index_preference = None
        decision_question_text = str(question_decision.get("question_text") or "").strip()
        decision_reason = str(question_decision.get("reason") or "decision_selector")
        decision_scenario_case_id = str(question_decision.get("scenario_case_id") or "").strip() or None
        decision_scenario_step_index = _safe_int(
            question_decision.get("scenario_step_index"),
            active_qa_scenario_step,
        )
        decision_action = str(question_decision.get("action") or "").strip().lower()
        decision_expected_signal = str(question_decision.get("expected_signal") or "").strip()
        decision_repeated_increment = max(0, _safe_int(question_decision.get("repeated_increment"), 0))
        completed_scenario_case_id = str(question_decision.get("completed_scenario_case_id") or "").strip() or None

        # Interview Engine v2 runtime intent/pressure rules.
        if engine_v2_enabled:
            policy_action = str(policy_decision.get("policy_action") or "continue")
            current_resume_phase = _to_interview_state_v2_phase(
                topic_phase=current_topic_phase,
                question_type=question_type,
            )
            resume_gate_passed = _resume_deep_dive_gate_opened(resume_evidence)
            resume_force_transition = _resume_deep_dive_force_transition(
                resume_scored_turns=resume_scored_turns_after,
            )
            resume_gate_forced = (
                (
                    str(current_phase_before_v2 or "") == "resume_deep_dive"
                    or current_resume_phase in {"intro", "resume_deep_dive"}
                )
                and not resume_gate_passed
                and not resume_force_transition
            ) or (policy_action == "resume_redirect" and not resume_force_transition)

            if resume_force_transition and str(current_phase_before_v2 or "") in {"intro", "resume_deep_dive"}:
                decision_action = "switch_topic"
                question_type = "main"
                will_advance = True
                should_end_now = False
                should_advance_scenario = True
                decision_reason = f"{decision_reason}_resume_turn_cap_force_technical_case"
                if trace is not None and not trace.get("selected_generator"):
                    trace["selected_generator"] = "strategist"

            if resume_gate_forced:
                decision_action = "ask_resume_followup"
                question_type, will_advance = _map_v2_action_to_legacy(decision_action)
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_resume_gate_hold"
            elif policy_action == "pressure_followup":
                decision_action = "pressure_followup"
                question_type, will_advance = _map_v2_action_to_legacy(decision_action)
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_pressure_followup_policy"
            elif policy_action == "give_example_scenario":
                decision_action = "clarify"
                question_type, will_advance = _map_v2_action_to_legacy(decision_action)
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_policy_give_example"
            elif policy_action in {"clarify", "answer_meta_then_redirect", "resume_redirect"}:
                decision_action = policy_action
                question_type, will_advance = _map_v2_action_to_legacy(decision_action)
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_policy_{policy_action}"
            elif not bool(policy_decision.get("advance_scenario", True)):
                decision_action = "pressure_followup"
                question_type, will_advance = _map_v2_action_to_legacy(decision_action)
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_policy_hold_scenario"

            forced_example_adaptation = (
                not resume_gate_forced
                and policy_action != "resume_redirect"
                and (
                    candidate_intent_type == "request_example"
                    or projected_no_case_streak_v2 >= 2
                )
            )
            if forced_example_adaptation:
                decision_action = "clarify"
                question_type, will_advance = _map_v2_action_to_legacy(decision_action)
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_forced_example_adaptation"

            post_policy_guarded = _apply_v2_question_guardrails(
                question_decision={
                    "action": decision_action,
                    "question_text": decision_question_text,
                    "reason": decision_reason,
                    "target_competency": str(question_decision.get("target_competency") or ""),
                    "difficulty": int(question_decision.get("difficulty") or adaptive_difficulty_tier),
                    "question_type": question_type,
                    "will_advance": will_advance,
                    "selected_topic_index": selected_topic_index_preference,
                    "scenario_case_id": decision_scenario_case_id,
                    "scenario_step_index": decision_scenario_step_index,
                    "expected_signal": decision_expected_signal,
                },
                role=interview.target_role,
                language=interview.language,
                asked_question_texts=asked_question_texts,
                transcript_summary=transcript_summary,
                current_competency=current_competency_for_guard,
                scenario_chains=role_scenario_chains,
                state_v2_before=state_v2_before,
                active_qa_scenario_id=active_qa_scenario_id,
                active_qa_scenario_step=active_qa_scenario_step,
            )
            decision_action = str(post_policy_guarded.get("action") or decision_action).strip().lower()
            decision_question_text = str(post_policy_guarded.get("question_text") or decision_question_text).strip()
            decision_reason = str(post_policy_guarded.get("reason") or decision_reason)
            decision_scenario_case_id = str(post_policy_guarded.get("scenario_case_id") or "").strip() or decision_scenario_case_id
            decision_scenario_step_index = _safe_int(
                post_policy_guarded.get("scenario_step_index"),
                decision_scenario_step_index,
            )
            question_type = str(post_policy_guarded.get("question_type") or question_type)
            will_advance = bool(post_policy_guarded.get("will_advance", will_advance))
            decision_expected_signal = str(post_policy_guarded.get("expected_signal") or decision_expected_signal)
            decision_repeated_increment = max(
                decision_repeated_increment,
                _safe_int(post_policy_guarded.get("repeated_increment"), 0),
            )
            rejected_generic = bool(
                post_policy_guarded.get("generic_guardrail_triggered")
                or post_policy_guarded.get("forbidden_generic_guardrail_triggered")
                or post_policy_guarded.get("simplify_context_guardrail_triggered")
            )
            rejected_repeated = bool(post_policy_guarded.get("question_repeated_guardrail_triggered"))
            if rejected_generic:
                redirect_fallback = (
                    _build_resume_deep_dive_followup(
                        language=interview.language,
                        resume_evidence=resume_evidence,
                        resume_context=resume_summary_for_strategy,
                    )
                    if (not _resume_deep_dive_gate_opened(resume_evidence) and not resume_force_transition)
                    else _runtime_followup_question_text(
                        language=interview.language,
                        followup_type="clarify",
                        role=interview.target_role,
                        topic=current_target,
                    )
                )
                decision_question_text = build_interviewer_redirect(
                    intent_result=candidate_intent,
                    state=state_v2_before or {},
                    role=interview.target_role,
                    language=interview.language,
                    resume_context=resume_summary_for_strategy,
                    current_scenario=active_qa_scenario_id,
                    fallback_question=redirect_fallback,
                )
                decision_action = "simplify"
                question_type = "clarification"
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_generic_rejected_redirect"
            elif rejected_repeated:
                redirect_fallback = _runtime_followup_question_text(
                    language=interview.language,
                    followup_type="clarify",
                    role=interview.target_role,
                    topic=current_target,
                )
                decision_question_text = build_interviewer_redirect(
                    intent_result=candidate_intent,
                    state=state_v2_before or {},
                    role=interview.target_role,
                    language=interview.language,
                    resume_context=resume_summary_for_strategy,
                    current_scenario=active_qa_scenario_id,
                    fallback_question=redirect_fallback,
                )
                decision_action = "follow_up"
                question_type = "followup"
                will_advance = False
                should_end_now = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
                decision_reason = f"{decision_reason}_repeat_rejected_redirect"
            if trace is not None:
                trace["generated_question_after_guardrails"] = decision_question_text or None
                trace["was_question_rejected_as_generic"] = bool(
                    trace.get("was_question_rejected_as_generic")
                    or rejected_generic
                )
                trace["was_question_rejected_as_repeated"] = bool(
                    trace.get("was_question_rejected_as_repeated")
                    or rejected_repeated
                )
                if trace["was_question_rejected_as_generic"] or trace["was_question_rejected_as_repeated"]:
                    trace["selected_generator"] = "interviewer_redirect"

        if completed_scenario_case_id and completed_scenario_case_id not in qa_completed_scenarios:
            qa_completed_scenarios.append(completed_scenario_case_id)
        if completed_scenario_case_id:
            completed_entry = (
                dict(qa_scenario_progress.get(completed_scenario_case_id))
                if isinstance(qa_scenario_progress.get(completed_scenario_case_id), dict)
                else {}
            )
            completed_entry["completed"] = True
            completed_entry["updated_at_turn"] = turn_count + 1
            qa_scenario_progress[completed_scenario_case_id] = completed_entry
        if decision_scenario_case_id:
            active_qa_scenario_id = decision_scenario_case_id
            active_qa_scenario_step = max(0, decision_scenario_step_index)
            scenario_progress_entry = (
                dict(qa_scenario_progress.get(decision_scenario_case_id))
                if isinstance(qa_scenario_progress.get(decision_scenario_case_id), dict)
                else {}
            )
            scenario_progress_entry["last_step_index"] = active_qa_scenario_step
            scenario_progress_entry["updated_at_turn"] = turn_count + 1
            if completed_scenario_case_id == decision_scenario_case_id:
                scenario_progress_entry["completed"] = True
            qa_scenario_progress[decision_scenario_case_id] = scenario_progress_entry
        if (
            decision_reason in {
                "interviewer_failure_detected_rephrase",
                "weak_answer_followup_required",
                "medium_answer_needs_refinement",
                "qa_chain_interviewer_failure_rephrase",
                "qa_chain_weak_answer_followup",
                "qa_chain_medium_answer_refine",
            }
            and interview.question_count < interview.max_questions
        ):
            should_end_now = False
        if engine_v2_enabled and decision_action == "close_interview":
            should_end_now = True
        if question_type == "clarification":
            next_pending_verification = pending_verification
        if not will_advance:
            forced_closure_reason = None

        resolved_next_topic_index: int | None = None
        next_q: str | None = None
        module_stage_key: str | None = None
        module_stage_title: str | None = None
        module_stage_prompt: str | None = None
        selected_target: dict | None = None
        workspace_ai_settings = state.get("workspace_ai_settings")
        if not should_end_now:
            competency_targets = None
            resume_anchor = None
            verification_target = None
            diversification_hint = None
            topic_phase = None
            question_block = None
            question_tier = None
            lead_question = None
            allowed_probes: list[str] = []
            scored_metrics: list[str] = []
            if topic_plan:
                current_idx = max(current_topic_index, 0)
                next_idx = interview.question_count
                target_idx = next_idx if will_advance else current_idx
                if will_advance:
                    if selected_topic_index_preference is not None and 0 <= selected_topic_index_preference < len(topic_plan):
                        resolved_next_topic_index = selected_topic_index_preference
                    elif _is_staged_module_type(module_type):
                        resolved_next_topic_index = min(current_idx + 1, len(topic_plan) - 1)
                    else:
                        resolved_next_topic_index = _resolve_next_topic_index(
                            topic_plan=topic_plan,
                                current_topic_index=current_idx,
                                default_next_index=target_idx,
                                close_reason=forced_closure_reason or saturation_reason,
                            )
                    target_idx = resolved_next_topic_index
                    if 0 <= target_idx < len(topic_plan):
                        target_topic = topic_plan[target_idx]
                        target_signature = _topic_signature_key(target_topic)
                        target_phase = str(target_topic.get("phase") or "").strip().lower()

                        if (
                            interview.target_role == "qa_engineer"
                            and target_phase == "behavioral_closing"
                        ):
                            qa_case_questions_asked = _qa_case_questions_asked_count(topic_plan, asked_topics)
                            qa_technical_signal_pct = _qa_technical_signal_percent(topic_plan, topic_signals, asked_topics)
                            qa_completed_case_count = len(
                                {
                                    str(item).strip()
                                    for item in qa_completed_scenarios
                                    if str(item).strip()
                                }
                            )
                            if (
                                qa_case_questions_asked < _QA_MIN_CASE_QUESTIONS
                                or qa_technical_signal_pct < _QA_MIN_TECHNICAL_SIGNAL_PCT
                                or qa_completed_case_count < _QA_MIN_SCENARIO_CASES
                            ):
                                fallback_technical_idx = _find_next_unasked_technical_topic_index(
                                    topic_plan,
                                    asked_topics=asked_topics,
                                    topic_signals=topic_signals,
                                )
                                if fallback_technical_idx is not None:
                                    resolved_next_topic_index = fallback_technical_idx
                                    target_idx = fallback_technical_idx
                                    adaptive_decision = (
                                        "deferred_until_qa_technical_signal"
                                        if qa_technical_signal_pct < _QA_MIN_TECHNICAL_SIGNAL_PCT
                                        else "deferred_until_qa_scenario_chain_minimum"
                                        if qa_completed_case_count < _QA_MIN_SCENARIO_CASES
                                        else "deferred_until_qa_case_minimum"
                                    )
                                else:
                                    logger.info(
                                        "QA behavioral gate could not find fallback technical slot: cases=%s signal_pct=%.1f completed_case_chains=%s",
                                        qa_case_questions_asked,
                                        qa_technical_signal_pct,
                                        qa_completed_case_count,
                                    )
                        elif target_signature and target_signature in set(covered_topics):
                            fallback_technical_idx = _find_next_unasked_technical_topic_index(
                                topic_plan,
                                asked_topics=asked_topics,
                                topic_signals=topic_signals,
                            )
                            if fallback_technical_idx is not None:
                                resolved_next_topic_index = fallback_technical_idx
                                target_idx = fallback_technical_idx
                                adaptive_decision = "deferred_duplicate_topic_signature"
                if target_idx < len(topic_plan):
                    target = topic_plan[target_idx]
                    selected_target = target
                    competency_targets = target.get("competencies")
                    resume_anchor = target.get("resume_anchor")
                    verification_target = target.get("verification_target")
                    topic_phase = target.get("phase")
                    question_block = target.get("block")
                    question_tier = target.get("tier")
                    lead_question = target.get("lead_question")
                    allowed_probes = list(target.get("allowed_probes") or [])
                    scored_metrics = list(target.get("scored_metrics") or [])
                    module_stage_key = target.get("stage_key")
                    module_stage_title = target.get("stage_title")
                    module_stage_prompt = target.get("stage_prompt")
                    if will_advance:
                        diversification_hint = _build_diversification_hint(
                            next_target=target,
                            current_target=current_target,
                            closed_reason=forced_closure_reason or saturation_reason,
                            language=interview.language,
                        )

            # ── Build InterviewContext ──────────────────────────────────────
            q_number = interview.question_count + 1 if will_advance else max(interview.question_count, 1)

            resume_context_for_interviewer = (
                str(resume_profile.get("interview_resume_context") or "").strip()
                or (resume.raw_text if resume else "")
            )

            ctx = InterviewContext(
                target_role=interview.target_role,
                seniority_level=interview.seniority_level,
                difficulty_tier=adaptive_difficulty_tier,
                question_number=q_number,
                max_questions=interview.max_questions,
                message_history=history,
                resume_text=resume_context_for_interviewer or None,
                template_questions=template_questions,
                competency_targets=competency_targets,
                language=interview.language,
                follow_up_count=topic_turns,
                last_answer_words=last_answer_words,
                shallow_reason=shallow_reason,
                answer_class=answer_class,
                question_type=question_type,
                mentioned_technologies=sorted(mentioned_technologies),
                verified_skills=sorted(verified_skills),
                contradiction_flags=contradiction_flags,
                pending_verification=next_pending_verification,
                topic_phase=topic_phase,
                question_block=question_block,
                question_tier=question_tier,
                lead_question=lead_question,
                allowed_probes=allowed_probes,
                scored_metrics=scored_metrics,
                resume_anchor=resume_anchor,
                verification_target=verification_target,
                diversification_hint=diversification_hint,
                candidate_memory=candidate_memory,
                current_topic=_topic_signature_key(selected_target or current_target),
                asked_topics=asked_topics,
                transcript_summary=transcript_summary,
                module_type=module_type,
                module_title=module_title,
                module_scenario_id=module_scenario_id,
                module_scenario_title=module_scenario_title,
                module_scenario_prompt=module_scenario_prompt,
                module_stage_key=module_stage_key,
                module_stage_title=module_stage_title,
                module_stage_prompt=module_stage_prompt,
                module_stage_index=resolved_next_topic_index if resolved_next_topic_index is not None else current_topic_index,
                module_stage_count=len(module_stage_plan) if module_stage_plan else 0,
            )
            if engine_v2_enabled:
                next_q = _sanitize_chat_question(decision_question_text, language=interview.language)
                if not next_q:
                    if candidate_intent_type in {
                        "clarification_request",
                        "request_example",
                        "confusion",
                        "meta_question",
                        "challenge_interviewer",
                        "request_resume_focus",
                    }:
                        redirect_fallback = (
                            _build_resume_deep_dive_followup(
                                language=interview.language,
                                resume_evidence=resume_evidence,
                                resume_context=resume_summary_for_strategy,
                            )
                            if (not _resume_deep_dive_gate_opened(resume_evidence) and not resume_force_transition)
                            else _runtime_followup_question_text(
                                language=interview.language,
                                followup_type="clarify",
                                role=interview.target_role,
                                topic=current_target,
                            )
                        )
                        next_q = build_interviewer_redirect(
                            intent_result=candidate_intent,
                            state=state_v2_before or {},
                            role=interview.target_role,
                            language=interview.language,
                            resume_context=resume_summary_for_strategy,
                            current_scenario=active_qa_scenario_id,
                            fallback_question=redirect_fallback,
                        )
                        decision_reason = f"{decision_reason}_v2_empty_question_redirect"
                        decision_action = "simplify"
                        question_type = "clarification"
                        will_advance = False
                        should_advance_scenario = False
                        if trace is not None:
                            trace["selected_generator"] = "interviewer_redirect"
                    elif answer_class in {"generic", "evasive", "no_experience_honest"} or str(runtime_answer_evaluation.get("quality") or "") == "weak":
                        next_q = build_pressure_followup(
                            role=interview.target_role,
                            current_question=current_question_text or "",
                            candidate_answer=message,
                            competency=_topic_primary_competency(current_target),
                            scenario_context=str(active_qa_scenario_id or ""),
                            language=interview.language,
                            answer_evaluation=runtime_answer_evaluation,
                        )
                        decision_reason = f"{decision_reason}_v2_empty_question_pressure_followup"
                        decision_action = "follow_up"
                        question_type = "followup"
                        will_advance = False
                        should_advance_scenario = False
                        if trace is not None:
                            trace["selected_generator"] = "pressure_followup"
                    else:
                        next_q = _build_resume_deep_dive_followup(
                            language=interview.language,
                            resume_evidence=resume_evidence,
                            resume_context=resume_summary_for_strategy,
                        )
                        decision_reason = f"{decision_reason}_v2_empty_question_resume_redirect"
                        decision_action = "follow_up"
                        question_type = "followup"
                        will_advance = False
                        should_advance_scenario = False
                        if trace is not None:
                            trace["selected_generator"] = "resume_redirect"
                    next_q = _sanitize_chat_question(next_q, language=interview.language)
            else:
                interviewer_model_preference = None
                if isinstance(workspace_ai_settings, dict):
                    interviewer_model_preference = workspace_ai_settings.get("interviewer_model_preference")
                next_q = await _get_next_question_with_dev_fallback(
                    ctx,
                    model_preference=interviewer_model_preference,
                )
                next_q = _sanitize_chat_question(next_q, language=interview.language)
                if decision_question_text:
                    next_q = _sanitize_chat_question(decision_question_text, language=interview.language)

            repeated_or_similar = False
            if next_q and _is_repeated_question_text(next_q, asked_question_texts):
                repeated_or_similar = True
            if (
                next_q
                and current_question_text
                and _question_text_similarity(next_q, current_question_text) >= 0.72
            ):
                repeated_or_similar = True
            if next_q and repeated_or_similar:
                if engine_v2_enabled:
                    should_force_example = candidate_intent_type == "request_example" or no_case_streak_v2 >= 2
                    redirect_fallback = (
                        build_pressure_followup(
                            role=interview.target_role,
                            current_question=current_question_text or "",
                            candidate_answer=message,
                            competency=_topic_primary_competency(current_target),
                            scenario_context=str(active_qa_scenario_id or ""),
                            language=interview.language,
                            answer_evaluation=runtime_answer_evaluation,
                            force_concrete_example=True,
                        )
                        if should_force_example
                        else _runtime_followup_question_text(
                            language=interview.language,
                            followup_type="clarify",
                            role=interview.target_role,
                            topic=current_target,
                        )
                    )
                    redirected = build_interviewer_redirect(
                        intent_result=candidate_intent,
                        state=state_v2_before or {},
                        role=interview.target_role,
                        language=interview.language,
                        resume_context=resume_summary_for_strategy,
                        current_scenario=active_qa_scenario_id,
                        fallback_question=redirect_fallback,
                    )
                    redirected = _sanitize_chat_question(redirected, language=interview.language)
                    if redirected and not _is_repeated_question_text(redirected, asked_question_texts):
                        next_q = redirected
                        decision_reason = f"{decision_reason}_repeat_runtime_redirect"
                        question_type = "clarification"
                        will_advance = False
                        should_advance_scenario = False
                        if trace is not None:
                            trace["selected_generator"] = "interviewer_redirect"
                            trace["was_question_rejected_as_repeated"] = True
                    elif should_force_example:
                        diversified = _sanitize_chat_question(redirect_fallback, language=interview.language)
                        if diversified and not _is_repeated_question_text(diversified, asked_question_texts):
                            next_q = diversified
                            decision_reason = f"{decision_reason}_repeat_runtime_forced_example"
                            question_type = "clarification"
                            will_advance = False
                            should_advance_scenario = False
                            if trace is not None:
                                trace["selected_generator"] = "pressure_followup"
                                trace["was_question_rejected_as_repeated"] = True
                else:
                    current_competency = ""
                    if isinstance(selected_target, dict):
                        competencies = selected_target.get("competencies")
                        if isinstance(competencies, list) and competencies:
                            current_competency = str(competencies[0] or "").strip()
                    diversified = _role_diversified_reframe_question(
                        role=interview.target_role,
                        competency=current_competency,
                        language=interview.language,
                    )
                    if diversified and not _is_repeated_question_text(diversified, asked_question_texts):
                        next_q = diversified
            if (
                next_q
                and _is_question_already_covered_in_transcript(next_q, transcript_summary)
                and _is_move_on_request(message)
            ):
                if engine_v2_enabled:
                    redirected = build_interviewer_redirect(
                        intent_result=candidate_intent,
                        state=state_v2_before or {},
                        role=interview.target_role,
                        language=interview.language,
                        resume_context=resume_summary_for_strategy,
                        current_scenario=active_qa_scenario_id,
                        fallback_question=_runtime_followup_question_text(
                            language=interview.language,
                            followup_type="clarify",
                            role=interview.target_role,
                            topic=current_target,
                        ),
                    )
                    redirected = _sanitize_chat_question(redirected, language=interview.language)
                    if redirected and not _is_repeated_question_text(redirected, asked_question_texts):
                        next_q = redirected
                        decision_reason = f"{decision_reason}_transcript_runtime_redirect"
                        question_type = "clarification"
                        will_advance = False
                        should_advance_scenario = False
                        if trace is not None:
                            trace["selected_generator"] = "interviewer_redirect"
                else:
                    current_competency = ""
                    if isinstance(selected_target, dict):
                        competencies = selected_target.get("competencies")
                        if isinstance(competencies, list) and competencies:
                            current_competency = str(competencies[0] or "").strip()
                    diversified = _role_diversified_reframe_question(
                        role=interview.target_role,
                        competency=current_competency,
                        language=interview.language,
                    )
                    if diversified and not _is_repeated_question_text(diversified, asked_question_texts):
                        next_q = diversified

        # ── Update DB state ─────────────────────────────────────────────────
        while len(topic_signals) <= current_topic_index:
            topic_signals.append("")
        if should_count_as_answer:
            topic_signals[current_topic_index] = _merge_topic_signal(
                topic_signals[current_topic_index],
                answer_class,
            )

        if should_count_as_answer:
            previous_candidate_answers = _append_answer_history(
                previous_candidate_answers,
                message,
                current_topic_index,
            )

        if should_end_now:
            topic_closed_reasons[current_topic_index] = adaptive_decision or "early_stop_low_signal"
            topic_mastered_flags[current_topic_index] = False
            interview.followup_depth = 0
            topic_turns = 0
            clarification_turns = 0
        elif will_advance:
            topic_closed_reasons[current_topic_index] = forced_closure_reason or saturation_reason or "advanced"
            topic_mastered_flags[current_topic_index] = bool(saturation_reason in {"topic_mastered", "topic_saturated"})
            interview.question_count += 1
            interview.followup_depth = 0
            topic_turns = 0
            clarification_turns = 0
            if resolved_next_topic_index is not None:
                current_topic_index = resolved_next_topic_index
            else:
                current_topic_index = max(interview.question_count - 1, 0)
        else:
            if question_type == "clarification":
                clarification_turns += 1
                interview.followup_depth = topic_turns
            else:
                clarification_turns = 0
                interview.followup_depth = topic_turns + 1
                topic_turns += 1

        turn_count += 1

        if next_q and _is_staged_module_type(module_type):
            assistant_turn = sum(1 for item in messages if item.role == "assistant") + 1
            history_stage_key = module_stage_key or current_target.get("stage_key")
            history_stage_title = module_stage_title or current_target.get("stage_title")
            if history_stage_key or history_stage_title:
                module_question_history.append(
                    {
                        "assistant_turn": assistant_turn,
                        "stage_key": history_stage_key,
                        "stage_title": history_stage_title,
                    }
                )

        if next_q and question_type == "main":
            topic_for_question = selected_target if will_advance else current_target
            question_signature = _topic_signature_key(topic_for_question)
            if question_signature and question_signature not in asked_topics:
                asked_topics.append(question_signature)
        if next_q and not _is_repeated_question_text(next_q, asked_question_texts):
            asked_question_texts.append(next_q)
        question_decision_history.append(
            {
                "at_turn": turn_count + 1,
                "reason": decision_reason,
                "action": decision_action or None,
                "expected_signal": decision_expected_signal or None,
                "target_competency": str(question_decision.get("target_competency") or ""),
                "difficulty": int(question_decision.get("difficulty") or adaptive_difficulty_tier),
                "question_type": question_type,
                "will_advance": will_advance,
                "selected_topic_index": selected_topic_index_preference if selected_topic_index_preference is not None else current_topic_index,
                "scenario_case_id": decision_scenario_case_id,
                "scenario_step_index": active_qa_scenario_step if decision_scenario_case_id else None,
                "completed_scenario_case_id": completed_scenario_case_id,
                "candidate_intent": candidate_intent_type,
                "scored_answer": should_count_as_answer,
                "conversational_intent": str(question_decision.get("conversational_intent") or ""),
                "information_target": str(question_decision.get("information_target") or ""),
            }
        )
        if will_advance or not bool(runtime_answer_evaluation.get("pressure_followup_required")):
            pressure_followup_last_key = ""

        interview.interview_state = {
            "turn_count": turn_count,
            "question_count": interview.question_count,
            "current_topic_index": current_topic_index,
            "topic_turns": topic_turns,
            "clarification_turns": clarification_turns,
            "resume_profile": resume_profile,
            "topic_plan": topic_plan,
            "topic_signals": topic_signals,
            "answer_classes": answer_classes,
            "mentioned_technologies": sorted(mentioned_technologies),
            "verified_skills": sorted(verified_skills),
            "probed_claim_targets": sorted(probed_claim_targets),
            "contradiction_flags": contradiction_flags,
            "pending_verification": next_pending_verification,
            "last_question_type": question_type,
            "last_answer_class": answer_class,
            "last_shallow_reason": shallow_reason,
            "last_answer_relevance": answer_relevance,
            "last_cross_topic_reuse": cross_topic_reuse,
            "previous_candidate_answers": previous_candidate_answers,
            "topic_reuse_flags": topic_reuse_flags,
            "topic_relevance_failures": topic_relevance_failures,
            "topic_closed_reasons": topic_closed_reasons,
            "topic_mastered_flags": topic_mastered_flags,
            "candidate_memory": candidate_memory,
            "asked_topics": asked_topics[-30:],
            "asked_question_texts": asked_question_texts[-30:],
            "transcript_summary": transcript_summary[-20:],
            "runtime_answer_evaluations": runtime_answer_evaluations[-80:],
            "last_runtime_answer_evaluation": runtime_answer_evaluation,
            "last_candidate_intent": candidate_intent,
            "question_decision_history": question_decision_history[-80:],
            "last_question_decision": question_decision_history[-1] if question_decision_history else None,
            "qa_scenario_progress": qa_scenario_progress,
            "active_qa_scenario_id": active_qa_scenario_id,
            "active_qa_scenario_step": active_qa_scenario_step,
            "qa_completed_scenarios": qa_completed_scenarios[-12:],
            "pressure_followup_last_key": pressure_followup_last_key,
            "candidate_answers_count": candidate_answers_count,
            "strong_answers_count": strong_answers_count,
            "weak_answers_count": weak_answers_count,
            "consecutive_strong_answers": consecutive_strong_answers,
            "low_relevance_answers_count": low_relevance_answers_count,
            "consecutive_weak_answers": consecutive_weak_answers,
            "nonsense_answers_count": nonsense_answers_count,
            "adaptive_difficulty_tier": adaptive_difficulty_tier,
            "adaptive_min_questions": max(1, min_questions_before_early_stop),
            "adaptive_role_max_cap": role_max_cap,
            "adaptive_last_decision": adaptive_decision,
            "module_type": module_type,
            "module_title": module_title or (_module_title_fallback(module_type) if module_type else None),
            "module_scenario_id": module_scenario_id,
            "module_scenario_title": module_scenario_title,
            "module_scenario_prompt": module_scenario_prompt,
            "module_stack_focus": module_stack_focus,
            "module_preferred_language": module_preferred_language,
            "module_workspace_hint": module_workspace_hint,
            "module_stage_plan": module_stage_plan,
            "module_stage_index": current_topic_index if _is_staged_module_type(module_type) else module_stage_index,
            "module_question_history": module_question_history,
        }
        if isinstance(workspace_ai_settings, dict) and workspace_ai_settings:
            interview.interview_state["workspace_ai_settings"] = {
                "proctoring_policy_mode": workspace_ai_settings.get("proctoring_policy_mode"),
                "interviewer_model_preference": workspace_ai_settings.get("interviewer_model_preference"),
                "assessor_model_preference": workspace_ai_settings.get("assessor_model_preference"),
            }
        if coding_task_artifact and _is_workspace_artifact_module_type(module_type):
            interview.interview_state["coding_task_artifact"] = {
                "language": _normalize_coding_task_language(coding_task_artifact.get("language")),
                "code": str(coding_task_artifact.get("code") or "")[:50000],
                "updated_at": coding_task_artifact.get("updated_at"),
            }
        if written_artifact and _is_written_artifact_module_type(module_type):
            interview.interview_state["written_artifact"] = {
                "content": str(written_artifact.get("content") or "")[:50000],
                "updated_at": written_artifact.get("updated_at"),
            }
        if engine_v2_enabled:
            current_target_competency = ""
            target_for_v2 = selected_target if isinstance(selected_target, dict) else current_target
            if isinstance(target_for_v2, dict):
                competencies = target_for_v2.get("competencies")
                if isinstance(competencies, list) and competencies:
                    current_target_competency = str(competencies[0] or "").strip()

            next_action = "follow_up"
            if should_end_now:
                next_action = "close_interview"
            elif question_type == "clarification":
                next_action = "simplify"
            elif will_advance and decision_scenario_case_id and active_qa_scenario_step == 0:
                next_action = "start_scenario"
            elif will_advance and decision_scenario_case_id:
                next_action = "continue_scenario"
            elif will_advance:
                next_action = "switch_topic"
            elif question_type == "main":
                next_action = "ask_new_topic"

            policy_action = str(policy_decision.get("policy_action") or "").strip()
            next_action = policy_action or decision_action or next_action
            covered_competencies = list(state_v2_before.get("covered_competencies", []) if isinstance(state_v2_before, dict) else [])
            validated_competencies = list(state_v2_before.get("validated_competencies", []) if isinstance(state_v2_before, dict) else [])
            weak_competencies = list(state_v2_before.get("weak_competencies", []) if isinstance(state_v2_before, dict) else [])
            if current_target_competency:
                if current_target_competency not in covered_competencies:
                    covered_competencies.append(current_target_competency)
                if should_count_as_answer and answer_class == "strong" and answer_relevance in {"medium", "high"}:
                    if current_target_competency not in validated_competencies:
                        validated_competencies.append(current_target_competency)
                    weak_competencies = [item for item in weak_competencies if item != current_target_competency]
                elif should_count_as_answer and (
                    answer_class in {"generic", "evasive", "no_experience_honest"} or answer_relevance == "low"
                ):
                    if current_target_competency not in weak_competencies:
                        weak_competencies.append(current_target_competency)
                if (
                    policy_action == "switch_topic"
                    and current_target_competency not in weak_competencies
                    and bool(policy_decision.get("update_weak_answer_count"))
                ):
                    weak_competencies.append(current_target_competency)

            derived_phase = _to_interview_state_v2_phase(
                topic_phase=str((selected_target or current_target or {}).get("phase") or ""),
                question_type=question_type,
            )
            resume_gate_passed_for_phase = _resume_deep_dive_gate_opened(resume_evidence)
            resume_force_transition_for_phase = _resume_deep_dive_force_transition(
                resume_scored_turns=resume_scored_turns_after,
            )
            if not resume_gate_passed_for_phase and not resume_force_transition_for_phase:
                derived_phase = "resume_deep_dive"
                will_advance = False
                should_advance_scenario = False
                decision_scenario_case_id = active_qa_scenario_id
                decision_scenario_step_index = max(0, active_qa_scenario_step)
            elif resume_force_transition_for_phase and derived_phase in {"intro", "resume_deep_dive"}:
                derived_phase = "technical_case"
            elif derived_phase == "intro":
                derived_phase = "resume_deep_dive"

            confusion_count_v2 = max(0, int((state_v2_before or {}).get("confusion_count", 0)))
            if bool(policy_decision.get("update_confusion_count")):
                confusion_count_v2 += 1
            last_conversational_intent = _derive_conversational_intent(
                raw_intent=str(question_decision.get("conversational_intent") or ""),
                action=decision_action,
                phase=derived_phase,
            )
            last_information_target = str(
                question_decision.get("information_target")
                or question_decision.get("target_competency")
                or current_target_competency
                or ""
            ).strip()
            semantic_streak_after = _conversational_intent_streak(
                conversational_intent_history,
                last_conversational_intent,
            )
            semantic_repeat_increment = 1 if semantic_streak_after >= 3 else 0
            repeated_question_count_v2 = max(
                0,
                int((state_v2_before or {}).get("repeated_question_count", 0))
                + decision_repeated_increment
                + semantic_repeat_increment,
            )
            semantic_repeated_question_count_v2 = max(
                0,
                semantic_repeated_question_count_before + semantic_repeat_increment,
            )
            if bool(policy_decision.get("update_weak_answer_count")):
                weak_answer_streak_v2 = weak_answer_streak_v2 + 1 if last_step_key_v2 == current_step_key else 1
            else:
                weak_answer_streak_v2 = 0
            if candidate_no_case_signal_now:
                no_case_streak_v2 += 1
            else:
                no_case_streak_v2 = 0

            if trace is not None:
                trace["current_phase_after"] = derived_phase
                trace["resume_evidence_after"] = dict(resume_evidence)
                trace["resume_gate_passed"] = _resume_deep_dive_gate_opened(resume_evidence)
                trace["resume_scored_turns_after"] = resume_scored_turns_after
                trace["resume_force_transition"] = resume_force_transition_for_phase
                trace["scenario_id"] = active_qa_scenario_id
                trace["scenario_step_after"] = max(0, int(active_qa_scenario_step or 0))
                trace["generated_question_after_guardrails"] = str(next_q or decision_question_text or "").strip() or None
                trace["conversational_intent"] = last_conversational_intent
                trace["information_target"] = last_information_target
                trace["semantic_repeat_streak"] = semantic_streak_after
                trace["semantic_repeat_detected"] = semantic_repeat_increment > 0
                if semantic_repeat_increment > 0:
                    trace["was_question_rejected_as_repeated"] = True
                phase_before = str(trace.get("current_phase_before") or "")
                if phase_before and phase_before != derived_phase:
                    trace["why_phase_advanced"] = f"{phase_before}->{derived_phase}:{decision_reason}"
                else:
                    trace["why_phase_advanced"] = f"phase_hold:{decision_reason}"
                if not trace.get("selected_generator"):
                    trace["selected_generator"] = "strategist"
                decision_traces_v2 = _append_v2_decision_trace(decision_traces_v2, trace, limit=20)

            fallback_counter_v2 = max(0, int((state_v2_before or {}).get("fallback_counter", 0)))
            strategist_json_valid_flag = bool(trace.get("strategist_json_valid")) if trace is not None else False
            selected_generator = str(trace.get("selected_generator") or "") if trace is not None else ""
            if selected_generator == "strategist" and strategist_json_valid_flag:
                fallback_counter_v2 = 0
            elif selected_generator:
                fallback_counter_v2 += 1

            interview_quality_metrics = _update_interview_quality_metrics(
                metrics=interview_quality_metrics_before,
                trace=trace,
                should_count_as_answer=should_count_as_answer,
                phase_after=derived_phase,
                policy_action=str(policy_decision.get("policy_action") or ""),
            )
            interview_quality_metrics["semantic_repeated_question_count"] = max(
                interview_quality_metrics.get("semantic_repeated_question_count", 0),
                semantic_repeated_question_count_v2,
            )

            if last_conversational_intent:
                conversational_intent_history.append(last_conversational_intent)
            if last_information_target:
                information_target_history.append(last_information_target)

            update_interview_state_v2(
                interview,
                {
                    "phase": derived_phase,
                    "role": interview.target_role,
                    "language": interview.language,
                    "current_competency": current_target_competency or None,
                    "current_scenario_id": active_qa_scenario_id,
                    "scenario_step": max(0, int(active_qa_scenario_step or 0)),
                    "attempts_on_current_step": 0
                    if will_advance
                    else max(
                        0,
                        int((state_v2_before or {}).get("attempts_on_current_step", 0)) + 1,
                    ),
                    "confusion_count": confusion_count_v2,
                    "repeated_question_count": repeated_question_count_v2,
                    "semantic_repeated_question_count": semantic_repeated_question_count_v2,
                    "covered_competencies": covered_competencies,
                    "validated_competencies": validated_competencies,
                    "weak_competencies": weak_competencies,
                    "asked_questions": asked_question_texts[-80:],
                    "conversational_intent_history": conversational_intent_history[-30:],
                    "information_target_history": information_target_history[-30:],
                    "last_answer_evaluation": runtime_answer_evaluation,
                    "next_action": next_action,
                    "resume_evidence": resume_evidence,
                    "resume_scored_turns": resume_scored_turns_after,
                    "weak_answer_streak": weak_answer_streak_v2,
                    "no_case_streak": no_case_streak_v2,
                    "last_step_key": current_step_key,
                    "current_step_key": current_step_key,
                    "last_policy_decision": policy_decision,
                    "decision_traces": decision_traces_v2[-20:],
                    "fallback_counter": fallback_counter_v2,
                    "interview_quality_metrics": interview_quality_metrics,
                },
            )
        if next_q:
            db.add(InterviewMessage(
                id=uuid.uuid4(),
                interview_id=interview.id,
                role="assistant",
                content=next_q,
            ))
            current_question = next_q
            response_is_followup = not will_advance
        else:
            current_question = None
            response_is_followup = False

    await db.commit()
    await db.refresh(interview)

    base_assistant_count = sum(1 for item in messages if item.role == "assistant")
    base_candidate_count = sum(1 for item in messages if item.role == "candidate")
    asked_questions_count = base_assistant_count + (1 if current_question else 0)
    answered_questions_count = base_candidate_count + 1

    return SendMessageResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        core_question_count=interview.question_count,
        asked_questions_count=asked_questions_count,
        answered_questions_count=answered_questions_count,
        current_question=current_question,
        is_followup=response_is_followup,
        question_type=question_type,
        interview_stage=_build_interview_stage_payload(interview),
        module_session=_build_interview_module_session_payload(interview),
    )


async def finish_interview(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> FinishInterviewResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    assessment_progress = await _get_assessment_progress(db, interview)

    if interview.status == "report_generated":
        existing_report = await db.scalar(
            select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
        )
        if not existing_report:
            raise InterviewAlreadyFinishedError()
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_generated",
            report_id=existing_report.id,
            summary=ReportSummary(
                overall_score=existing_report.overall_score,
                hiring_recommendation=existing_report.hiring_recommendation,
                interview_summary=existing_report.interview_summary,
            ),
            assessment_progress=assessment_progress,
            interview_stage=_build_interview_stage_payload(interview),
            module_session=_build_interview_module_session_payload(interview),
        )
    if interview.status == "report_processing":
        _schedule_report_generation(interview.id)
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_processing",
            report_id=None,
            summary=None,
            assessment_progress=assessment_progress,
            interview_stage=_build_interview_stage_payload(interview),
            module_session=_build_interview_module_session_payload(interview),
        )
    if interview.status != "in_progress":
        raise InterviewNotActiveError()

    if interview.question_count < interview.max_questions:
        raise MaxQuestionsNotReachedError()

    # Mark as processing and generate report asynchronously if needed.
    prior_status = interview.status
    finished_at = datetime.utcnow()
    interview.status = "report_processing"
    interview.completed_at = finished_at

    if interview.company_assessment_id:
        from app.models.company_assessment import CompanyAssessment
        from app.services.assessment_invite_service import (
            build_assessment_progress_payload,
            get_current_assessment_module_payload,
            sync_assessment_module_progress,
        )

        assessment = await db.scalar(
            select(CompanyAssessment).where(CompanyAssessment.id == interview.company_assessment_id)
        )
        if assessment:
            module_plan, current_module_index, current_module = get_current_assessment_module_payload(assessment)
            current_interview_id = current_module.get("interview_id") if current_module else None
            has_next_module = (
                current_module is not None
                and current_interview_id == str(interview.id)
                and current_module_index + 1 < len(module_plan)
            )
            if has_next_module:
                sync_assessment_module_progress(
                    assessment,
                    completed_interview_id=interview.id,
                    completed_at=finished_at,
                )
                assessment.status = "in_progress"
                assessment.interview_id = None
                assessment.completed_at = None
                assessment_progress = AssessmentProgressResponse(
                    **build_assessment_progress_payload(
                        assessment,
                        interview_id=interview.id,
                    )
                )

    _update_report_diagnostics(interview, phase="finish_sync", status="processing")
    await db.commit()
    await db.refresh(interview)
    assessment_progress = await _get_assessment_progress(db, interview) or assessment_progress
    _increment_report_pipeline_metric("finish_sync_started_total")
    _log_report_pipeline_event(
        "finish_sync_started",
        interview_id=interview.id,
        timeout_seconds=_sync_report_generation_timeout_seconds(),
    )

    sync_started_at = time.perf_counter()
    try:
        report = await asyncio.wait_for(
            _ensure_report_generated(db, interview, candidate),
            timeout=_sync_report_generation_timeout_seconds(),
        )
        duration_seconds = round(time.perf_counter() - sync_started_at, 3)
        _increment_report_pipeline_metric("finish_sync_succeeded_total")
        _log_report_pipeline_event(
            "finish_sync_succeeded",
            interview_id=interview.id,
            duration_seconds=duration_seconds,
            report_id=str(report.id),
        )
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_generated",
            report_id=report.id,
            summary=ReportSummary(
                overall_score=report.overall_score,
                hiring_recommendation=report.hiring_recommendation,
                interview_summary=report.interview_summary,
            ),
            assessment_progress=await _get_assessment_progress(db, interview) or assessment_progress,
            interview_stage=_build_interview_stage_payload(interview),
            module_session=_build_interview_module_session_payload(interview),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Synchronous report generation timed out for interview %s, switching to async processing",
            interview.id,
        )
        duration_seconds = round(time.perf_counter() - sync_started_at, 3)
        _increment_report_pipeline_metric("finish_sync_timeout_total")
        _log_report_pipeline_event(
            "finish_sync_timeout",
            interview_id=interview.id,
            duration_seconds=duration_seconds,
        )
        interview.status = "report_processing"
        _update_report_diagnostics(interview, phase="finish_sync_timeout", status="processing")
        await db.commit()
        _schedule_report_generation(interview.id)
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_processing",
            report_id=None,
            summary=None,
            assessment_progress=await _get_assessment_progress(db, interview) or assessment_progress,
            interview_stage=_build_interview_stage_payload(interview),
            module_session=_build_interview_module_session_payload(interview),
        )
    except Exception as exc:
        logger.exception("Initial report generation failed for interview %s, switching to async processing", interview.id)
        duration_seconds = round(time.perf_counter() - sync_started_at, 3)
        _increment_report_pipeline_metric("finish_sync_error_total")
        _log_report_pipeline_event(
            "finish_sync_error",
            interview_id=interview.id,
            duration_seconds=duration_seconds,
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        interview.status = "report_processing"
        _update_report_diagnostics(
            interview,
            phase="finish_sync_error",
            status="processing",
            error=str(exc),
        )
        await db.commit()
        _schedule_report_generation(interview.id)
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_processing",
            report_id=None,
            summary=None,
            assessment_progress=await _get_assessment_progress(db, interview) or assessment_progress,
            interview_stage=_build_interview_stage_payload(interview),
            module_session=_build_interview_module_session_payload(interview),
        )

async def _ensure_report_generated(
    db: AsyncSession,
    interview: Interview,
    candidate: Candidate,
) -> AssessmentReport:
    assess_started_at = time.perf_counter()
    existing_report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )
    if existing_report:
        if interview.status != "report_generated":
            interview.status = "report_generated"
        _update_report_diagnostics(interview, phase="existing_report", status="ready")
        await db.commit()
        _increment_report_pipeline_metric("report_existing_hit_total")
        _log_report_pipeline_event(
            "report_existing_hit",
            interview_id=interview.id,
            report_id=str(existing_report.id),
        )
        return existing_report

    messages = await _get_messages(db, interview.id)
    _update_report_diagnostics(interview, phase="assessing", status="processing")
    await db.commit()
    result: AssessmentResult = await _assess_with_dev_fallback(
        target_role=interview.target_role,
        message_history=_to_history(messages),
        message_timestamps=_to_timestamps(messages),
        behavioral_signals=interview.behavioral_signals,
        language=interview.language,
        interview_meta=interview.interview_state or {},
    )
    result = _apply_low_confidence_verdict_guard(result)
    if not isinstance(result.full_report_json, dict):
        result.full_report_json = {}

    confidence_verdict = str(result.full_report_json.get("confidence_verdict") or _confidence_verdict_for_value(result.overall_confidence))
    evidence_v2 = _compute_scoring_v2_evidence(
        target_role=interview.target_role,
        competency_scores=result.competency_scores,
        competency_confidence=result.competency_confidence,
        per_question_analysis=result.per_question_analysis,
        interview_meta=interview.interview_state if isinstance(interview.interview_state, dict) else None,
        evidence_coverage=result.evidence_coverage,
    )
    result = _apply_scoring_v2_recommendation_policy(
        result=result,
        confidence_verdict=confidence_verdict,
        validated_competencies_count=len(evidence_v2.get("validated_competencies", [])),
    )
    proficiency_profile = _derive_proficiency_profile(
        target_role=interview.target_role,
        overall_score=result.overall_score,
        hard_skills_score=result.hard_skills_score,
        problem_solving_score=result.problem_solving_score,
        communication_score=result.communication_score,
        overall_confidence=result.overall_confidence,
        language=interview.language,
        confidence_verdict=confidence_verdict,
        validated_competencies_count=len(evidence_v2.get("validated_competencies", [])),
        has_completed_scenario_with_strong_evidence=bool(evidence_v2.get("has_completed_scenario_with_strong_evidence")),
        has_strategy_ownership_evidence=bool(evidence_v2.get("has_strategy_ownership_evidence")),
        interview_meta=interview.interview_state if isinstance(interview.interview_state, dict) else None,
    )
    if confidence_verdict == "insufficient_data":
        level_why = (
            "Сигнал недостаточный: confidence < 40%, поэтому уровень предварительный и требует дополнительного интервью."
            if interview.language == "ru"
            else "Signal is insufficient: confidence < 40%, so the level is provisional and requires additional interview evidence."
        )
    elif confidence_verdict == "needs_human_review":
        level_why = (
            "Надёжность сигнала средняя (40–70%), поэтому финальный уровень требует ручной валидации интервьюером."
            if interview.language == "ru"
            else "Signal confidence is moderate (40–70%), so final level assignment requires human reviewer validation."
        )
    else:
        level_why = (
            "Уровень определён по подтверждённым компетенциям, глубине кейсов и качеству ответов, а не по резюме."
            if interview.language == "ru"
            else "The level is determined by validated competencies, case depth, and answer evidence, not by resume claims."
        )

    human_followup_questions = _build_scoring_v2_human_followup_questions(
        language=interview.language,
        weak_competencies=list(evidence_v2.get("weak_competencies", [])),
        unanswered_competencies=list(evidence_v2.get("unanswered_competencies", [])),
    )

    result.full_report_json["proficiency_profile"] = proficiency_profile
    result.full_report_json["scoring_v2"] = {
        "version": "v2",
        "evidence_table": list(evidence_v2.get("evidence_table", [])),
        "validated_competencies": list(evidence_v2.get("validated_competencies", [])),
        "weak_competencies": list(evidence_v2.get("weak_competencies", [])),
        "unanswered_competencies": list(evidence_v2.get("unanswered_competencies", [])),
        "why_this_level": level_why,
        "human_followup_questions": human_followup_questions,
        "confidence_verdict": confidence_verdict,
        "validated_competencies_count": len(evidence_v2.get("validated_competencies", [])),
        "strong_answer_count": int(evidence_v2.get("strong_answer_count", 0)),
        "case_depth_ratio": float(evidence_v2.get("case_depth_ratio", 0.0)),
    }
    result.full_report_json["validated_competencies"] = list(evidence_v2.get("validated_competencies", []))
    result.full_report_json["weak_competencies"] = list(evidence_v2.get("weak_competencies", []))
    result.full_report_json["unanswered_competencies"] = list(evidence_v2.get("unanswered_competencies", []))
    result.full_report_json["evidence_table"] = list(evidence_v2.get("evidence_table", []))
    result.full_report_json["human_followup_questions"] = human_followup_questions

    report = AssessmentReport(
        id=uuid.uuid4(),
        interview_id=interview.id,
        candidate_id=interview.candidate_id,
        overall_score=result.overall_score,
        hard_skills_score=result.hard_skills_score,
        soft_skills_score=result.soft_skills_score,
        communication_score=result.communication_score,
        problem_solving_score=result.problem_solving_score,
        strengths=result.strengths,
        weaknesses=result.weaknesses,
        recommendations=result.recommendations,
        hiring_recommendation=result.hiring_recommendation,
        interview_summary=result.interview_summary,
        model_version=result.model_version,
        full_report_json=result.full_report_json,
        competency_scores=result.competency_scores or None,
        per_question_analysis=result.per_question_analysis or None,
        skill_tags=result.skill_tags or None,
        red_flags=result.red_flags or None,
        response_consistency=result.response_consistency,
        cheat_risk_score=result.cheat_risk_score,
        cheat_flags=result.cheat_flags or None,
        overall_confidence=result.overall_confidence,
        competency_confidence=result.competency_confidence or None,
        confidence_reasons=result.confidence_reasons or None,
        evidence_coverage=result.evidence_coverage or None,
        decision_policy_version=result.decision_policy_version,
    )
    db.add(report)
    await db.flush()

    if result.skill_tags:
        _save_skills(db, interview.candidate_id, report.id, result.skill_tags)

    interview.status = "report_generated"
    _update_report_diagnostics(interview, phase="report_saved", status="ready")
    await db.commit()
    await db.refresh(report)
    duration_seconds = round(time.perf_counter() - assess_started_at, 3)
    _increment_report_pipeline_metric("report_generated_total")
    _log_report_pipeline_event(
        "report_generated",
        interview_id=interview.id,
        report_id=str(report.id),
        duration_seconds=duration_seconds,
        hiring_recommendation=report.hiring_recommendation,
    )

    if interview.company_assessment_id:
        from app.services.assessment_invite_service import sync_assessment_status

        await sync_assessment_status(db, interview.id)

    try:
        from app.models.user import User
        from app.services.email_service import send_new_candidate_to_company, send_report_ready

        user = await db.scalar(select(User).where(User.id == candidate.user_id))
        role_label = interview.target_role.replace("_", " ").title()

        if user:
            await send_report_ready(
                candidate_email=user.email,
                candidate_name=candidate.full_name,
                role=role_label,
                overall_score=report.overall_score or 0,
                report_id=str(report.id),
                app_url=settings.APP_URL,
            )

        if interview.company_assessment_id:
            from app.models.company import Company
            from app.models.company_assessment import CompanyAssessment

            assessment = await db.scalar(
                select(CompanyAssessment).where(CompanyAssessment.id == interview.company_assessment_id)
            )
            if assessment:
                company = await db.scalar(select(Company).where(Company.id == assessment.company_id))
                company_user = (
                    await db.scalar(select(User).where(User.id == company.owner_user_id))
                    if company else None
                )
                if company and company_user:
                    await send_new_candidate_to_company(
                        company_email=company_user.email,
                        company_name=company.name,
                        candidate_name=candidate.full_name,
                        candidate_email=user.email if user else "",
                        role=role_label,
                        overall_score=report.overall_score or 0,
                        hiring_recommendation=report.hiring_recommendation,
                        candidate_id=str(candidate.id),
                        app_url=settings.APP_URL,
                    )
    except Exception as email_exc:
        logger.warning("Email notification failed: %s", email_exc)

    return report


def _schedule_report_generation(interview_id: uuid.UUID) -> None:
    if interview_id in _REPORT_GENERATION_TASKS:
        _increment_report_pipeline_metric("report_schedule_skipped_duplicate_total")
        _log_report_pipeline_event(
            "report_schedule_skipped_duplicate",
            interview_id=interview_id,
            active_tasks=len(_REPORT_GENERATION_TASKS),
        )
        return
    _REPORT_GENERATION_TASKS.add(interview_id)
    _increment_report_pipeline_metric("report_schedule_enqueued_total")
    _log_report_pipeline_event(
        "report_schedule_enqueued",
        interview_id=interview_id,
        active_tasks=len(_REPORT_GENERATION_TASKS),
    )
    asyncio.create_task(_run_report_generation_job(interview_id))


async def _run_report_generation_job(interview_id: uuid.UUID) -> None:
    lock_owner = str(uuid.uuid4())
    lock_acquired = False
    job_started_at = time.perf_counter()
    _increment_report_pipeline_metric("report_async_job_started_total")
    _log_report_pipeline_event(
        "report_async_job_started",
        interview_id=interview_id,
    )
    try:
        async with AsyncSessionLocal() as lock_session:
            lock_acquired = await _try_acquire_report_generation_lock(
                lock_session,
                interview_id,
                owner=lock_owner,
            )
        if not lock_acquired:
            logger.debug(
                "Skipped async report generation for interview %s because lock is already held",
                interview_id,
            )
            _increment_report_pipeline_metric("report_lock_contended_total")
            _log_report_pipeline_event(
                "report_lock_contended",
                interview_id=interview_id,
            )
            return
        _increment_report_pipeline_metric("report_lock_acquired_total")
        _log_report_pipeline_event(
            "report_lock_acquired",
            interview_id=interview_id,
        )

        max_attempts = _report_max_auto_retries()
        for attempt_number in range(1, max_attempts + 1):
            phase = f"async_worker_attempt_{attempt_number}"
            attempt_started_at = time.perf_counter()
            _increment_report_pipeline_metric("report_async_attempt_started_total")
            _log_report_pipeline_event(
                "report_async_attempt_started",
                interview_id=interview_id,
                attempt=attempt_number,
                max_attempts=max_attempts,
            )
            try:
                async with AsyncSessionLocal() as session:
                    interview = await session.scalar(select(Interview).where(Interview.id == interview_id))
                    if not interview:
                        _increment_report_pipeline_metric("report_async_missing_interview_total")
                        _log_report_pipeline_event(
                            "report_async_missing_interview",
                            interview_id=interview_id,
                            attempt=attempt_number,
                        )
                        return

                    existing_report = await session.scalar(
                        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
                    )
                    if existing_report:
                        if interview.status != "report_generated":
                            interview.status = "report_generated"
                        _update_report_diagnostics(
                            interview,
                            phase="async_existing_report",
                            status="ready",
                        )
                        await session.commit()
                        _increment_report_pipeline_metric("report_async_existing_hit_total")
                        _log_report_pipeline_event(
                            "report_async_existing_hit",
                            interview_id=interview_id,
                            attempt=attempt_number,
                            duration_seconds=round(time.perf_counter() - attempt_started_at, 3),
                        )
                        return

                    candidate = await session.scalar(select(Candidate).where(Candidate.id == interview.candidate_id))
                    if not candidate:
                        interview.status = "failed"
                        _update_report_diagnostics(
                            interview,
                            phase=phase,
                            status="failed",
                            error=f"Candidate {interview.candidate_id} not found",
                        )
                        await session.commit()
                        _increment_report_pipeline_metric("report_async_missing_candidate_total")
                        _log_report_pipeline_event(
                            "report_async_missing_candidate",
                            interview_id=interview_id,
                            attempt=attempt_number,
                        )
                        return

                    interview.status = "report_processing"
                    _update_report_diagnostics(
                        interview,
                        phase=phase,
                        status="processing",
                    )
                    await session.commit()
                    await _ensure_report_generated(session, interview, candidate)
                    _increment_report_pipeline_metric("report_async_attempt_succeeded_total")
                    _log_report_pipeline_event(
                        "report_async_attempt_succeeded",
                        interview_id=interview_id,
                        attempt=attempt_number,
                        duration_seconds=round(time.perf_counter() - attempt_started_at, 3),
                    )
                    return
            except Exception as exc:
                is_last_attempt = attempt_number >= max_attempts
                _increment_report_pipeline_metric("report_async_attempt_failed_total")
                _log_report_pipeline_event(
                    "report_async_attempt_failed",
                    interview_id=interview_id,
                    attempt=attempt_number,
                    max_attempts=max_attempts,
                    error_type=exc.__class__.__name__,
                    error=str(exc),
                    duration_seconds=round(time.perf_counter() - attempt_started_at, 3),
                )
                if is_last_attempt:
                    logger.exception(
                        "Async report generation exhausted retries for interview %s",
                        interview_id,
                    )
                    async with AsyncSessionLocal() as session:
                        interview = await session.scalar(select(Interview).where(Interview.id == interview_id))
                        if interview and interview.status != "report_generated":
                            interview.status = "failed"
                            _update_report_diagnostics(
                                interview,
                                phase=phase,
                                status="failed",
                                error=str(exc),
                            )
                            await session.commit()
                    _increment_report_pipeline_metric("report_async_job_failed_total")
                    _log_report_pipeline_event(
                        "report_async_job_failed",
                        interview_id=interview_id,
                        attempts=attempt_number,
                        error_type=exc.__class__.__name__,
                        error=str(exc),
                        duration_seconds=round(time.perf_counter() - job_started_at, 3),
                    )
                    return

                backoff_seconds = _compute_report_retry_backoff_seconds(attempt_number)
                next_retry_at_iso = (
                    datetime.utcnow() + timedelta(seconds=backoff_seconds)
                ).isoformat()
                logger.warning(
                    "Async report generation attempt %s failed for interview %s; retry in %ss",
                    attempt_number,
                    interview_id,
                    backoff_seconds,
                )
                async with AsyncSessionLocal() as session:
                    interview = await session.scalar(select(Interview).where(Interview.id == interview_id))
                    if interview and interview.status != "report_generated":
                        interview.status = "report_processing"
                        _update_report_diagnostics(
                            interview,
                            phase=phase,
                            status="processing",
                            error=str(exc),
                            next_retry_at=next_retry_at_iso,
                        )
                        await session.commit()
                _log_report_pipeline_event(
                    "report_async_retry_scheduled",
                    interview_id=interview_id,
                    attempt=attempt_number,
                    next_retry_at=next_retry_at_iso,
                    backoff_seconds=backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)
                continue
    except Exception:
        logger.exception("Async report generation crashed for interview %s", interview_id)
        _increment_report_pipeline_metric("report_async_worker_crash_total")
        _log_report_pipeline_event(
            "report_async_worker_crash",
            interview_id=interview_id,
            duration_seconds=round(time.perf_counter() - job_started_at, 3),
        )
        async with AsyncSessionLocal() as session:
            interview = await session.scalar(select(Interview).where(Interview.id == interview_id))
            if interview and interview.status != "report_generated":
                interview.status = "failed"
                _update_report_diagnostics(
                    interview,
                    phase="async_worker",
                    status="failed",
                    error="Unexpected async worker crash",
                )
                await session.commit()
    finally:
        if lock_acquired:
            async with AsyncSessionLocal() as lock_session:
                await _release_report_generation_lock(
                    lock_session,
                    interview_id,
                    owner=lock_owner,
                )
        _REPORT_GENERATION_TASKS.discard(interview_id)
        _increment_report_pipeline_metric("report_async_job_finished_total")
        _log_report_pipeline_event(
            "report_async_job_finished",
            interview_id=interview_id,
            lock_acquired=lock_acquired,
            active_tasks=len(_REPORT_GENERATION_TASKS),
            duration_seconds=round(time.perf_counter() - job_started_at, 3),
            metrics={
                "job_started": _REPORT_PIPELINE_METRICS.get("report_async_job_started_total", 0),
                "job_finished": _REPORT_PIPELINE_METRICS.get("report_async_job_finished_total", 0),
                "job_failed": _REPORT_PIPELINE_METRICS.get("report_async_job_failed_total", 0),
            },
        )


async def get_interview_report_status(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> InterviewReportStatusResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    assessment_progress = await _get_assessment_progress(db, interview)
    report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )

    if report:
        diagnostics = _read_report_diagnostics(interview)
        if interview.status != "report_generated" or not diagnostics or diagnostics.get("last_status") != "ready":
            interview.status = "report_generated"
            _update_report_diagnostics(interview, phase="status_poll", status="ready")
            await db.commit()
            diagnostics = _read_report_diagnostics(interview)
        return InterviewReportStatusResponse(
            interview_id=interview.id,
            status="report_generated",
            processing_state="ready",
            report_id=report.id,
            summary=ReportSummary(
                overall_score=report.overall_score,
                hiring_recommendation=report.hiring_recommendation,
                interview_summary=report.interview_summary,
            ),
            failure_reason=None,
            diagnostics=diagnostics,
            assessment_progress=assessment_progress,
            interview_stage=_build_interview_stage_payload(interview),
            module_session=_build_interview_module_session_payload(interview),
        )

    if interview.status == "failed":
        state = "failed"
    elif interview.status in {"completed", "report_processing"}:
        state = "processing"
    else:
        state = "pending"

    diagnostics = _read_report_diagnostics(interview)
    failure_reason = diagnostics.get("last_error") if diagnostics else None
    if state == "failed" and not failure_reason:
        failure_reason = "Report generation failed."

    if state == "processing":
        _schedule_report_generation(interview.id)

    return InterviewReportStatusResponse(
        interview_id=interview.id,
        status=interview.status,
        processing_state=state,
        report_id=None,
        summary=None,
        failure_reason=failure_reason,
        diagnostics=diagnostics,
        assessment_progress=assessment_progress,
        interview_stage=_build_interview_stage_payload(interview),
        module_session=_build_interview_module_session_payload(interview),
    )


async def retry_interview_report_generation(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> InterviewReportStatusResponse:
    interview = await _get_interview(db, interview_id, candidate.id)

    report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )
    if report:
        _increment_report_pipeline_metric("report_manual_retry_skipped_ready_total")
        _log_report_pipeline_event(
            "report_manual_retry_skipped_ready",
            interview_id=interview.id,
            report_id=str(report.id),
        )
        return await get_interview_report_status(db, candidate, interview.id)

    if interview.status in {"created", "in_progress"}:
        raise ReportRetryNotAllowedError(
            "Interview is still in progress. Complete all questions before retrying report generation."
        )
    if interview.question_count < interview.max_questions:
        raise ReportRetryNotAllowedError(
            "Interview is incomplete. Finish the interview before retrying report generation."
        )
    if interview.status not in {"failed", "completed", "report_processing"}:
        raise ReportRetryNotAllowedError("Report retry is not available for this interview state.")

    prior_status = interview.status
    interview.status = "report_processing"
    _update_report_diagnostics(interview, phase="manual_retry", status="processing")
    await db.commit()
    _increment_report_pipeline_metric("report_manual_retry_requested_total")
    _log_report_pipeline_event(
        "report_manual_retry_requested",
        interview_id=interview.id,
        prior_status=prior_status,
    )
    _schedule_report_generation(interview.id)

    return InterviewReportStatusResponse(
        interview_id=interview.id,
        status=interview.status,
        processing_state="processing",
        report_id=None,
        summary=None,
        failure_reason=None,
        diagnostics=_read_report_diagnostics(interview),
        assessment_progress=await _get_assessment_progress(db, interview),
        interview_stage=_build_interview_stage_payload(interview),
        module_session=_build_interview_module_session_payload(interview),
    )


async def get_interview_detail(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> InterviewDetailResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    assessment_progress = await _get_assessment_progress(db, interview)
    messages = await _get_messages(db, interview.id)

    report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )
    if not report and interview.status in {"completed", "report_processing"}:
        _schedule_report_generation(interview.id)

    # Exclude system messages from API response
    visible = [
        InterviewMessageResponse(role=m.role, content=m.content, created_at=m.created_at)
        for m in messages
        if m.role != "system"
    ]
    progress_counters = _build_progress_counters(
        core_question_count=interview.question_count,
        messages=messages,
    )

    return InterviewDetailResponse(
        interview_id=interview.id,
        status=interview.status,
        target_role=interview.target_role,
        seniority_level=interview.seniority_level,
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        core_question_count=progress_counters["core_question_count"],
        asked_questions_count=progress_counters["asked_questions_count"],
        answered_questions_count=progress_counters["answered_questions_count"],
        language=interview.language,
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        messages=visible,
        has_report=report is not None,
        report_id=report.id if report else None,
        assessment_progress=assessment_progress,
        interview_stage=_build_interview_stage_payload(interview),
        module_session=_build_interview_module_session_payload(interview),
    )


async def get_interview_debug_trace(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> dict[str, Any]:
    interview = await _get_interview(db, interview_id, candidate.id)
    state_v2 = get_interview_state_v2(interview)
    traces_raw = state_v2.get("decision_traces")
    traces = list(traces_raw) if isinstance(traces_raw, list) else []
    interview_quality_metrics = _normalize_interview_quality_metrics(state_v2.get("interview_quality_metrics"))
    live_smoke_summary = _build_live_smoke_summary(interview_quality_metrics)
    return {
        "interview_id": interview.id,
        "engine_version": str(state_v2.get("engine_version") or "v1"),
        "trace_count": len(traces[-20:]),
        "traces": traces[-20:],
        "interview_quality_metrics": interview_quality_metrics,
        "live_smoke_summary": live_smoke_summary,
    }


async def get_coding_task_artifact(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> CodingTaskArtifactResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    _ensure_coding_task_interview(interview)
    return _build_coding_task_artifact_response(interview)


async def save_coding_task_artifact(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
    *,
    code: str,
    language: str | None = None,
) -> CodingTaskArtifactResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    _ensure_coding_task_interview(interview)
    if interview.status != "in_progress":
        raise InterviewNotActiveError()

    state = dict(interview.interview_state or {})
    state["coding_task_artifact"] = {
        "language": _normalize_coding_task_language(language),
        "code": str(code or "")[:50000],
        "updated_at": datetime.utcnow().isoformat(),
    }
    interview.interview_state = state
    await db.commit()
    await db.refresh(interview)
    return _build_coding_task_artifact_response(interview)


async def get_written_artifact(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> WrittenArtifactResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    _ensure_written_interview(interview)
    return _build_written_artifact_response(interview)


async def save_written_artifact(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
    *,
    content: str,
) -> WrittenArtifactResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    _ensure_written_interview(interview)
    if interview.status != "in_progress":
        raise InterviewNotActiveError()

    state = dict(interview.interview_state or {})
    state["written_artifact"] = {
        "content": str(content or "")[:50000],
        "updated_at": datetime.utcnow().isoformat(),
    }
    interview.interview_state = state
    await db.commit()
    await db.refresh(interview)
    return _build_written_artifact_response(interview)


async def save_interview_recording(
    db: AsyncSession,
    candidate_id: uuid.UUID,
    interview_id: uuid.UUID,
    file,  # UploadFile
) -> None:
    import os
    from fastapi import HTTPException, status
    from app.core.config import settings

    interview = await _get_interview(db, interview_id, candidate_id)

    os.makedirs(settings.RECORDING_STORAGE_DIR, exist_ok=True)
    allowed_types = {
        "video/webm": ".webm",
        "video/mp4": ".mp4",
    }
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported recording format. Allowed: video/webm, video/mp4.",
        )

    max_bytes = settings.MAX_RECORDING_SIZE_MB * 1024 * 1024
    dest = os.path.join(
        settings.RECORDING_STORAGE_DIR,
        f"{interview_id}{allowed_types[file.content_type]}",
    )
    written = 0

    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 64)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Recording exceeds maximum allowed size of {settings.MAX_RECORDING_SIZE_MB} MB.",
                    )
                out.write(chunk)
    except HTTPException:
        if os.path.exists(dest):
            os.remove(dest)
        raise

    interview.recording_path = dest
    await db.commit()


async def save_behavioral_signals(
    db: AsyncSession,
    candidate_id: uuid.UUID,
    interview_id: uuid.UUID,
    signals: dict,
) -> None:
    """Persist behavioral signals captured during the interview."""
    interview = await _get_interview(db, interview_id, candidate_id)
    payload = dict(signals or {})
    workspace_ai_settings = (
        interview.interview_state.get("workspace_ai_settings")
        if isinstance(interview.interview_state, dict)
        else None
    )
    if payload.get("policy_mode") in (None, "") and isinstance(workspace_ai_settings, dict):
        payload["policy_mode"] = workspace_ai_settings.get("proctoring_policy_mode")
    interview.behavioral_signals = normalize_behavioral_signals(payload)
    await db.commit()


def build_proctoring_timeline_response(
    *,
    interview_id: uuid.UUID,
    report_id: uuid.UUID | None,
    signals: dict | None,
) -> ProctoringTimelineResponse:
    payload = get_proctoring_timeline_payload(signals)
    return ProctoringTimelineResponse(
        interview_id=interview_id,
        report_id=report_id,
        policy_mode=payload["policy_mode"],
        risk_level=payload["risk_level"],
        total_events=payload["total_events"],
        high_severity_count=payload["high_severity_count"],
        speech_activity_pct=payload["speech_activity_pct"],
        silence_pct=payload["silence_pct"],
        long_silence_count=payload["long_silence_count"],
        speech_segment_count=payload["speech_segment_count"],
        events=payload["events"],
    )


async def get_interview_replay(
    db: AsyncSession,
    interview_id: uuid.UUID,
    company_id: uuid.UUID,
) -> InterviewReplayResponse | None:
    """Return a Q&A replay annotated with per-question analysis and transcript."""
    interview = await db.scalar(select(Interview).where(Interview.id == interview_id))
    if not interview:
        return None

    if interview.company_assessment_id:
        from app.models.company_assessment import CompanyAssessment

        assessment = await db.scalar(
            select(CompanyAssessment).where(CompanyAssessment.id == interview.company_assessment_id)
        )
        if not assessment or assessment.company_id != company_id:
            return None

    messages = await _get_messages(db, interview.id)
    report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )

    # Load candidate name
    candidate = await db.scalar(select(Candidate).where(Candidate.id == interview.candidate_id))
    if interview.company_assessment_id is None and (
        not candidate or not await has_company_candidate_workspace_access(db, company_id, candidate)
    ):
        return None
    candidate_name = candidate.full_name if candidate else "Unknown"

    # Build turns: pair assistant messages with following candidate messages
    per_q: list[dict] = report.per_question_analysis or [] if report else []
    module_stage_map = _build_module_stage_map(interview)

    turns: list[ReplayTurn] = []
    transcript_blocks: list[TranscriptBlockResponse] = []
    visible = [m for m in messages if m.role in ("assistant", "candidate")]
    q_num = 0
    i = 0
    while i < len(visible):
        msg = visible[i]
        if msg.role == "assistant":
            q_num += 1
            question_msg = msg
            answer_msg = visible[i + 1] if i + 1 < len(visible) and visible[i + 1].role == "candidate" else None
            analysis = per_q[q_num - 1] if q_num - 1 < len(per_q) else None
            stage_meta = module_stage_map.get(q_num, {})
            turns.append(ReplayTurn(
                question_number=q_num,
                question=question_msg.content,
                answer=answer_msg.content if answer_msg else "",
                question_time=question_msg.created_at,
                answer_time=answer_msg.created_at if answer_msg else None,
                analysis=analysis,
                stage_key=stage_meta.get("stage_key"),
                stage_title=stage_meta.get("stage_title"),
            ))
            transcript_blocks.append(
                TranscriptBlockResponse(
                    speaker="interviewer",
                    kind="question",
                    turn_number=q_num,
                    text=question_msg.content,
                    timestamp=question_msg.created_at,
                )
            )
            transcript_blocks.append(
                TranscriptBlockResponse(
                    speaker="candidate",
                    kind="answer",
                    turn_number=q_num,
                    text=answer_msg.content if answer_msg else "",
                    timestamp=answer_msg.created_at if answer_msg else None,
                )
            )
            i += 2 if answer_msg else 1
        else:
            i += 1

    transcript_text_parts: list[str] = []
    for block in transcript_blocks:
        speaker_label = "Interviewer" if block.speaker == "interviewer" else "Candidate"
        kind_label = f"Q{block.turn_number}" if block.kind == "question" else f"A{block.turn_number}"
        header_parts = [kind_label, speaker_label]
        if block.timestamp:
            header_parts.append(block.timestamp.isoformat())
        transcript_text_parts.append(" | ".join(header_parts))
        transcript_text_parts.append(block.text.strip() or "[no answer captured]")
        transcript_text_parts.append("")

    transcript_text = "\n".join(transcript_text_parts).strip() if transcript_text_parts else None

    return InterviewReplayResponse(
        interview_id=interview.id,
        candidate_id=interview.candidate_id,
        candidate_name=candidate_name,
        target_role=interview.target_role,
        seniority_level=interview.seniority_level,
        completed_at=interview.completed_at,
        turns=turns,
        transcript_blocks=transcript_blocks,
        transcript_text=transcript_text,
        module_session=_build_interview_module_session_payload(interview),
    )


async def list_interviews(
    db: AsyncSession,
    candidate: Candidate,
) -> list:
    from app.schemas.interview import InterviewListItemResponse
    result = await db.scalars(
        select(Interview)
        .where(Interview.candidate_id == candidate.id)
        .order_by(Interview.started_at.desc())
    )
    interviews = list(result)

    items = []
    for interview in interviews:
        messages = await _get_messages(db, interview.id)
        progress_counters = _build_progress_counters(
            core_question_count=interview.question_count,
            messages=messages,
        )
        report = await db.scalar(
            select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
        )
        items.append(InterviewListItemResponse(
            interview_id=interview.id,
            status=interview.status,
            target_role=interview.target_role,
            seniority_level=interview.seniority_level,
            question_count=interview.question_count,
            max_questions=interview.max_questions,
            core_question_count=progress_counters["core_question_count"],
            asked_questions_count=progress_counters["asked_questions_count"],
            answered_questions_count=progress_counters["answered_questions_count"],
            started_at=interview.started_at,
            completed_at=interview.completed_at,
            has_report=report is not None,
            report_id=report.id if report else None,
        ))
    return items
