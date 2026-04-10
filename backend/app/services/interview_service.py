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
from app.ai.competencies import build_interview_plan
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
    FinishInterviewResponse,
    InterviewDetailResponse,
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
)
from app.services.candidate_access_service import has_company_candidate_workspace_access


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
_CODING_TASK_MODULE_TYPE = "coding_task"
_SYSTEM_DESIGN_STAGE_KEYS = (
    "requirements",
    "high_level_design",
    "tradeoffs",
)
_CODING_TASK_STAGE_KEYS = (
    "task_brief",
    "implementation",
    "review",
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
_CODING_TASK_SCENARIOS: dict[str, dict[str, str]] = {
    "backend_engineer": {
        "scenario_id": "rate_limiter_window_counter",
        "title_en": "a request rate limiter",
        "title_ru": "лимитер запросов",
        "prompt_en": "Implement a function that enforces a per-user sliding-window rate limit. Explain edge cases, data structures, and test coverage.",
        "prompt_ru": "Реализуйте функцию, которая ограничивает запросы пользователя по sliding-window rate limit. Объясните edge cases, структуры данных и покрытие тестами.",
    },
    "frontend_engineer": {
        "scenario_id": "async_search_state_manager",
        "title_en": "an async search state manager",
        "title_ru": "менеджер состояния async-поиска",
        "prompt_en": "Implement the core logic for a debounced async search state manager with cancellation, stale-response protection, and loading/error states.",
        "prompt_ru": "Реализуйте core logic для debounced async search state manager с cancelation, защитой от stale responses и состояниями loading/error.",
    },
    "qa_engineer": {
        "scenario_id": "flaky_test_classifier",
        "title_en": "a flaky test classifier",
        "title_ru": "классификатор flaky-тестов",
        "prompt_en": "Implement logic that groups repeated test runs, detects flaky failures, and emits a stable summary for CI diagnostics.",
        "prompt_ru": "Реализуйте логику, которая группирует повторные прогоны тестов, выявляет flaky failures и формирует стабильную сводку для CI-диагностики.",
    },
    "devops_engineer": {
        "scenario_id": "deployment_rollout_guard",
        "title_en": "a deployment rollout guard",
        "title_ru": "guard для rollout-деплоя",
        "prompt_en": "Implement logic that evaluates service rollout health from metrics/events and decides whether to continue, pause, or roll back deployment.",
        "prompt_ru": "Реализуйте логику, которая по метрикам и событиям rollout оценивает здоровье сервиса и решает: продолжать, поставить на паузу или откатить деплой.",
    },
    "data_scientist": {
        "scenario_id": "feature_freshness_monitor",
        "title_en": "a feature freshness monitor",
        "title_ru": "монитор свежести фичей",
        "prompt_en": "Implement logic that validates feature freshness for scoring requests, applies fallbacks, and explains why a record should be blocked or allowed.",
        "prompt_ru": "Реализуйте логику, которая проверяет свежесть фичей для scoring-запросов, применяет fallback и объясняет, почему запись нужно заблокировать или пропустить.",
    },
    "product_manager": {
        "scenario_id": "experiment_guardrail_parser",
        "title_en": "an experiment guardrail parser",
        "title_ru": "парсер guardrail-метрик эксперимента",
        "prompt_en": "Implement logic that validates experiment guardrail metrics, flags invalid inputs, and produces a rollout recommendation payload for decision makers.",
        "prompt_ru": "Реализуйте логику, которая валидирует guardrail-метрики эксперимента, флагирует некорректные входы и формирует payload с рекомендацией по rollout.",
    },
    "mobile_engineer": {
        "scenario_id": "offline_sync_queue",
        "title_en": "an offline sync queue",
        "title_ru": "offline sync queue",
        "prompt_en": "Implement the core queue logic for offline sync with retries, conflict markers, and battery-friendly batching.",
        "prompt_ru": "Реализуйте core logic очереди offline sync с retry, conflict markers и батчингом, который бережёт батарею.",
    },
    "designer": {
        "scenario_id": "design_token_transformer",
        "title_en": "a design token transformer",
        "title_ru": "трансформер design tokens",
        "prompt_en": "Implement logic that transforms design tokens into platform-specific output, validates required fields, and surfaces actionable errors.",
        "prompt_ru": "Реализуйте логику, которая преобразует design tokens в platform-specific output, валидирует обязательные поля и возвращает понятные ошибки.",
    },
}
_CODING_TASK_DEFAULT_SCENARIO = {
    "scenario_id": "structured_business_rule_engine",
    "title_en": "a structured business-rule evaluator",
    "title_ru": "структурированный rule evaluator",
    "prompt_en": "Implement a function that evaluates structured rules, returns deterministic decisions, and explains edge cases and test coverage.",
    "prompt_ru": "Реализуйте функцию, которая оценивает структурированные правила, возвращает детерминированное решение и объясняет edge cases и покрытие тестами.",
}


def _module_title_fallback(module_type: str) -> str:
    return module_type.replace("_", " ").strip().title() or "Assessment Module"


def _is_staged_module_type(module_type: str | None) -> bool:
    return module_type in {_SYSTEM_DESIGN_MODULE_TYPE, _CODING_TASK_MODULE_TYPE}


def _select_system_design_scenario(
    target_role: str,
    language: str,
    module_config: dict[str, Any] | None,
) -> dict[str, str]:
    config = module_config if isinstance(module_config, dict) else {}
    scenario = dict(_SYSTEM_DESIGN_SCENARIOS.get(target_role, _SYSTEM_DESIGN_DEFAULT_SCENARIO))
    requested_id = str(config.get("scenario_id") or "").strip()
    if requested_id and requested_id == scenario.get("scenario_id"):
        pass
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
    scenario = dict(_CODING_TASK_SCENARIOS.get(target_role, _CODING_TASK_DEFAULT_SCENARIO))
    title_override = str(config.get("scenario_title") or "").strip()
    prompt_override = str(config.get("scenario_prompt") or "").strip()
    is_en = language == "en"
    return {
        "scenario_id": str(config.get("scenario_id") or scenario["scenario_id"]).strip() or scenario["scenario_id"],
        "title": title_override or (scenario["title_en"] if is_en else scenario["title_ru"]),
        "prompt": prompt_override or (scenario["prompt_en"] if is_en else scenario["prompt_ru"]),
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
        stage_key=str(current_stage.get("stage_key") or state.get("module_stage_key") or "") or None,
        stage_title=str(current_stage.get("stage_title") or state.get("module_stage_title") or "") or None,
        stage_index=current_stage_index,
        stage_count=stage_count,
    )


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
_MAX_CHAT_QUESTION_WORDS = 28

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
    "qa_engineer": 8,
    "product_manager": 8,
    "designer": 8,
}
_ADAPTIVE_MIN_QUESTIONS_FLOOR = 10
_ADAPTIVE_EXTENSION_STEP = 4
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


def _estimate_dynamic_question_budget(
    *,
    target_role: str,
    resume_profile: dict | None,
) -> tuple[int, int, int]:
    """Return (initial_max_questions, role_max_cap, min_questions_before_early_stop)."""
    role_cap = _ROLE_MAX_QUESTION_CAP.get(target_role, 32)
    role_floor = _ROLE_MIN_QUESTION_FLOOR.get(target_role, _ADAPTIVE_MIN_QUESTIONS_FLOOR)
    profile = resume_profile or {}

    technologies = list(profile.get("technologies", []) or [])
    project_highlights = list(profile.get("project_highlights", []) or [])
    experience_years = profile.get("experience_years")
    seniority_hint = str(profile.get("seniority_hint") or "").strip().lower()

    has_resume_signal = bool(
        technologies
        or project_highlights
        or experience_years is not None
        or seniority_hint
    )
    if not has_resume_signal:
        # Preserve legacy behavior for sparse/noisy resumes.
        initial = MAX_QUESTIONS
        return initial, initial, initial + 1

    budget = _ROLE_BASE_QUESTION_BUDGET.get(target_role, 16)

    years = _safe_int(experience_years, 0)
    if years >= 10:
        budget += 8
    elif years >= 7:
        budget += 6
    elif years >= 5:
        budget += 4
    elif years >= 3:
        budget += 2

    if seniority_hint in {"staff", "senior"}:
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

    if len(compact) > 170:
        compact = compact[:170].rsplit(" ", 1)[0].rstrip(" ,.;:!?") + "?"

    if not compact.endswith("?"):
        compact = compact.rstrip(" ,.;:") + "?"

    if len(compact.split()) < 4:
        return (
            "Can you walk me through one concrete production example?"
            if language == "en"
            else "Можете разобрать один конкретный пример из вашей практики?"
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


async def _get_next_question_with_dev_fallback(
    ctx: InterviewContext,
    model_preference: str | None = None,
) -> str:
    try:
        return await interviewer.get_next_question(ctx, model_override=model_preference)
    except Exception as exc:
        if settings.is_local_or_test:
            logger.exception(
                "Interviewer generation failed in local/test mode; using deterministic fallback",
            )
            try:
                return await MockInterviewer().get_next_question(ctx, model_override=model_preference)
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
        if settings.is_local_or_test:
            logger.exception(
                "Assessment generation failed in local/test mode; using deterministic fallback",
            )
            try:
                fallback_result = await MockAssessor().assess(
                    target_role=target_role,
                    message_history=message_history,
                    message_timestamps=message_timestamps,
                    behavioral_signals=behavioral_signals,
                    language=language,
                    interview_meta=interview_meta,
                    model_override=assessor_model_preference,
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


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def start_interview(
    db: AsyncSession,
    candidate: Candidate,
    target_role: str,
    template_id: uuid.UUID | None = None,
    language: str = "ru",
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
    safe_workspace_ai_settings = workspace_ai_settings if isinstance(workspace_ai_settings, dict) else {}

    resume_profile = preprocess_resume(active_resume.raw_text, target_role)
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
    elif normalized_module_type == _CODING_TASK_MODULE_TYPE:
        topic_plan, module_context = _build_coding_task_topic_plan(
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
    ctx = InterviewContext(
        target_role=target_role,
        question_number=1,
        max_questions=max_q,
        message_history=[],
        resume_text=active_resume.raw_text,
        template_questions=template.questions if template else None,
        competency_targets=topic_plan[0]["competencies"] if topic_plan else None,
        language=language,
        resume_anchor=topic_plan[0].get("resume_anchor") if topic_plan else None,
        verification_target=topic_plan[0].get("verification_target") if topic_plan else None,
        topic_phase=topic_plan[0].get("phase") if topic_plan else None,
        candidate_memory=[],
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
    initial_state = {
        "turn_count": 1,
        "question_count": 1,
        "current_topic_index": 0,
        "topic_turns": 0,
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
        "candidate_answers_count": 0,
        "strong_answers_count": 0,
        "weak_answers_count": 0,
        "low_relevance_answers_count": 0,
        "consecutive_weak_answers": 0,
        "nonsense_answers_count": 0,
        "adaptive_min_questions": min_questions_before_early_stop,
        "adaptive_role_max_cap": role_max_cap,
        "adaptive_last_decision": None,
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
                "module_stage_plan": list((module_context or {}).get("stage_plan") or []),
                "module_stage_index": 0,
                "module_question_history": list((module_context or {}).get("question_history") or []),
            }
        )
    interview.interview_state = initial_state
    interview.status = "in_progress"
    await db.commit()
    await db.refresh(interview)

    return StartInterviewResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        current_question=first_question,
        language=interview.language,
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
        import json
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
        last_question_type: str = str(state.get("last_question_type", "main"))
        candidate_memory: list[str] = list(state.get("candidate_memory", []))
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
        if _is_staged_module_type(module_type) and topic_plan:
            current_topic_index = min(max(module_stage_index, 0), len(topic_plan) - 1)
        candidate_answers_count = _safe_int(state.get("candidate_answers_count"), 0)
        strong_answers_count = _safe_int(state.get("strong_answers_count"), 0)
        weak_answers_count = _safe_int(state.get("weak_answers_count"), 0)
        low_relevance_answers_count = _safe_int(state.get("low_relevance_answers_count"), 0)
        consecutive_weak_answers = _safe_int(state.get("consecutive_weak_answers"), 0)
        nonsense_answers_count = _safe_int(state.get("nonsense_answers_count"), 0)
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
        answer_classes.append(answer_class)
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
        answer_relevance = _answer_relevance(
            question=current_question_text,
            answer=message,
            new_techs=new_techs,
            current_claim_target=claim_target,
        )
        is_nonsense_answer = _is_noise_or_nonsense_answer(message)
        cross_topic_reuse = _is_cross_topic_reuse(message, previous_candidate_answers, current_topic_index)

        while len(topic_reuse_flags) <= current_topic_index:
            topic_reuse_flags.append(False)
        while len(topic_relevance_failures) <= current_topic_index:
            topic_relevance_failures.append(0)
        while len(topic_closed_reasons) <= current_topic_index:
            topic_closed_reasons.append("")
        while len(topic_mastered_flags) <= current_topic_index:
            topic_mastered_flags.append(False)

        if cross_topic_reuse and answer_relevance == "low":
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

        # ── Session memory + adaptive quality counters ─────────────────────
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
        if is_weak_signal:
            weak_answers_count += 1
            consecutive_weak_answers += 1
        else:
            consecutive_weak_answers = 0
        if answer_relevance == "low":
            low_relevance_answers_count += 1
        if is_nonsense_answer:
            nonsense_answers_count += 1

        if _is_staged_module_type(module_type):
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
        topic_guard_closure_reason: str | None = None

        if _is_staged_module_type(module_type):
            if last_question_type != "main":
                question_type = "main"
                will_advance = True
            elif answer_class in {"no_experience_honest", "generic", "evasive"} or answer_relevance == "low":
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
            elif answer_class in {"no_experience_honest", "generic", "evasive"} and can_probe_current_topic:
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
            elif topic_guard_requires_probe:
                normalized_claim_target = str(claim_target or "").strip().lower()
                question_type = "claim_verification"
                next_pending_verification = normalized_claim_target
                probed_claim_targets.add(normalized_claim_target)
                will_advance = False

            elif can_probe_claim and ranked_claim_target and answer_class in {"generic", "evasive", "no_experience_honest"}:
                question_type = "claim_verification"
                next_pending_verification = ranked_claim_target
                probed_claim_targets.add(ranked_claim_target)
                will_advance = False

            elif answer_class == "no_experience_honest" and can_probe_current_topic:
                question_type = "followup"
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

        resolved_next_topic_index: int | None = None
        next_q: str | None = None
        module_stage_key: str | None = None
        module_stage_title: str | None = None
        module_stage_prompt: str | None = None
        workspace_ai_settings = state.get("workspace_ai_settings")
        if not should_end_now:
            competency_targets = None
            resume_anchor = None
            verification_target = None
            diversification_hint = None
            topic_phase = None
            if topic_plan:
                current_idx = max(current_topic_index, 0)
                next_idx = interview.question_count
                target_idx = next_idx if will_advance else current_idx
                if will_advance:
                    if _is_staged_module_type(module_type):
                        resolved_next_topic_index = min(current_idx + 1, len(topic_plan) - 1)
                    else:
                        resolved_next_topic_index = _resolve_next_topic_index(
                            topic_plan=topic_plan,
                            current_topic_index=current_idx,
                            default_next_index=target_idx,
                            close_reason=forced_closure_reason or saturation_reason,
                        )
                    target_idx = resolved_next_topic_index
                if target_idx < len(topic_plan):
                    target = topic_plan[target_idx]
                    competency_targets = target.get("competencies")
                    resume_anchor = target.get("resume_anchor")
                    verification_target = target.get("verification_target")
                    topic_phase = target.get("phase")
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

            ctx = InterviewContext(
                target_role=interview.target_role,
                question_number=q_number,
                max_questions=interview.max_questions,
                message_history=history,
                resume_text=resume.raw_text if resume else None,
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
                resume_anchor=resume_anchor,
                verification_target=verification_target,
                diversification_hint=diversification_hint,
                candidate_memory=candidate_memory,
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
            interviewer_model_preference = None
            if isinstance(workspace_ai_settings, dict):
                interviewer_model_preference = workspace_ai_settings.get("interviewer_model_preference")
            next_q = await _get_next_question_with_dev_fallback(
                ctx,
                model_preference=interviewer_model_preference,
            )
            next_q = _sanitize_chat_question(next_q, language=interview.language)

        # ── Update DB state ─────────────────────────────────────────────────
        while len(topic_signals) <= current_topic_index:
            topic_signals.append("")
        topic_signals[current_topic_index] = _merge_topic_signal(
            topic_signals[current_topic_index],
            answer_class,
        )

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
        elif will_advance:
            topic_closed_reasons[current_topic_index] = forced_closure_reason or saturation_reason or "advanced"
            topic_mastered_flags[current_topic_index] = bool(saturation_reason in {"topic_mastered", "topic_saturated"})
            interview.question_count += 1
            interview.followup_depth = 0
            topic_turns = 0
            if resolved_next_topic_index is not None:
                current_topic_index = resolved_next_topic_index
            else:
                current_topic_index = max(interview.question_count - 1, 0)
        else:
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

        interview.interview_state = {
            "turn_count": turn_count,
            "question_count": interview.question_count,
            "current_topic_index": current_topic_index,
            "topic_turns": topic_turns,
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
            "candidate_answers_count": candidate_answers_count,
            "strong_answers_count": strong_answers_count,
            "weak_answers_count": weak_answers_count,
            "low_relevance_answers_count": low_relevance_answers_count,
            "consecutive_weak_answers": consecutive_weak_answers,
            "nonsense_answers_count": nonsense_answers_count,
            "adaptive_min_questions": max(1, min_questions_before_early_stop),
            "adaptive_role_max_cap": role_max_cap,
            "adaptive_last_decision": adaptive_decision,
            "module_type": module_type,
            "module_title": module_title or (_module_title_fallback(module_type) if module_type else None),
            "module_scenario_id": module_scenario_id,
            "module_scenario_title": module_scenario_title,
            "module_scenario_prompt": module_scenario_prompt,
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

    return SendMessageResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        current_question=current_question,
        is_followup=response_is_followup,
        question_type=question_type,
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

    return InterviewDetailResponse(
        interview_id=interview.id,
        status=interview.status,
        target_role=interview.target_role,
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        language=interview.language,
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        messages=visible,
        has_report=report is not None,
        report_id=report.id if report else None,
        assessment_progress=assessment_progress,
        module_session=_build_interview_module_session_payload(interview),
    )


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
        report = await db.scalar(
            select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
        )
        items.append(InterviewListItemResponse(
            interview_id=interview.id,
            status=interview.status,
            target_role=interview.target_role,
            question_count=interview.question_count,
            max_questions=interview.max_questions,
            started_at=interview.started_at,
            completed_at=interview.completed_at,
            has_report=report is not None,
            report_id=report.id if report else None,
        ))
    return items
