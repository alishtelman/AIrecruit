"""
Interview service — owns all interview business logic.
Routers call these functions; no SQLAlchemy queries in routers.

question_count is an explicit DB column on Interview, incremented here.
It is the authoritative source of truth — no need to re-count messages.
"""
import asyncio
import logging
import uuid
from datetime import datetime
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assessor import AssessmentResult, assessor
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
    FinishInterviewResponse,
    InterviewDetailResponse,
    InterviewReportStatusResponse,
    InterviewMessageResponse,
    ProctoringTimelineResponse,
    InterviewReplayResponse,
    ReplayTurn,
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

    if not normalized_events:
        synthesized = _synthesize_events_from_counters(payload)
        normalized_events = [
            _normalize_event(item, index=idx, policy_mode=policy_mode)
            for idx, item in enumerate(synthesized)
        ]

    payload["policy_mode"] = policy_mode
    payload["events"] = normalized_events
    payload["captured_at"] = datetime.utcnow().isoformat()
    return payload


def get_proctoring_timeline_payload(signals: dict | None) -> dict[str, Any]:
    normalized = normalize_behavioral_signals(signals)
    events = list(normalized.get("events", []))
    high_count = sum(1 for event in events if event.get("severity") == "high")
    medium_count = sum(1 for event in events if event.get("severity") == "medium")

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


async def _get_next_question_with_dev_fallback(ctx: InterviewContext) -> str:
    try:
        return await interviewer.get_next_question(ctx)
    except Exception as exc:
        if settings.is_local_or_test:
            logger.exception(
                "Interviewer generation failed in local/test mode; using deterministic fallback",
            )
            try:
                return await MockInterviewer().get_next_question(ctx)
            except Exception:
                logger.exception("Deterministic interviewer fallback also failed")
        raise RuntimeError("AI interviewer request failed") from exc


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

    resume_profile = preprocess_resume(active_resume.raw_text, target_role)
    if template:
        max_q = len(template.questions)
        role_max_cap = max_q
        min_questions_before_early_stop = min(_ADAPTIVE_MIN_QUESTIONS_FLOOR, max_q)
    else:
        max_q, role_max_cap, min_questions_before_early_stop = _estimate_dynamic_question_budget(
            target_role=target_role,
            resume_profile=resume_profile,
        )
    topic_plan = build_interview_plan(target_role, max_q, resume_profile)

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
        candidate_memory=[],
    )
    first_question = await _get_next_question_with_dev_fallback(ctx)

    db.add(InterviewMessage(
        id=uuid.uuid4(),
        interview_id=interview.id,
        role="assistant",
        content=first_question,
    ))

    # question_count tracks core interview questions only
    interview.question_count = 1
    interview.interview_state = {
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
        "adaptive_min_questions": min_questions_before_early_stop,
        "adaptive_role_max_cap": role_max_cap,
        "adaptive_last_decision": None,
    }
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
        import json
        for msg in messages:
            if msg.role == "system":
                try:
                    plan_data = json.loads(msg.content)
                    topic_plan = plan_data.get("topic_plan", [])
                    resume_profile = plan_data.get("resume_profile", {})
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
        candidate_answers_count = _safe_int(state.get("candidate_answers_count"), 0)
        strong_answers_count = _safe_int(state.get("strong_answers_count"), 0)
        weak_answers_count = _safe_int(state.get("weak_answers_count"), 0)
        low_relevance_answers_count = _safe_int(state.get("low_relevance_answers_count"), 0)
        consecutive_weak_answers = _safe_int(state.get("consecutive_weak_answers"), 0)
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
        )
        interview.max_questions = adapted_max_questions

        # ── Contradiction detection ─────────────────────────────────────────
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
        if not should_end_now:
            competency_targets = None
            resume_anchor = None
            verification_target = None
            diversification_hint = None
            if topic_plan:
                current_idx = max(current_topic_index, 0)
                next_idx = interview.question_count
                target_idx = next_idx if will_advance else current_idx
                if will_advance:
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
                resume_anchor=resume_anchor,
                verification_target=verification_target,
                diversification_hint=diversification_hint,
                candidate_memory=candidate_memory,
            )
            next_q = await _get_next_question_with_dev_fallback(ctx)

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
            "adaptive_min_questions": max(1, min_questions_before_early_stop),
            "adaptive_role_max_cap": role_max_cap,
            "adaptive_last_decision": adaptive_decision,
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
    )


async def finish_interview(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> FinishInterviewResponse:
    interview = await _get_interview(db, interview_id, candidate.id)

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
        )
    if interview.status == "report_processing":
        _schedule_report_generation(interview.id)
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_processing",
            report_id=None,
            summary=None,
        )
    if interview.status != "in_progress":
        raise InterviewNotActiveError()

    if interview.question_count < interview.max_questions:
        raise MaxQuestionsNotReachedError()

    # Mark as processing and generate report asynchronously if needed.
    interview.status = "report_processing"
    interview.completed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(interview)

    try:
        report = await _ensure_report_generated(db, interview, candidate)
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_generated",
            report_id=report.id,
            summary=ReportSummary(
                overall_score=report.overall_score,
                hiring_recommendation=report.hiring_recommendation,
                interview_summary=report.interview_summary,
            ),
        )
    except Exception:
        logger.exception("Initial report generation failed for interview %s, switching to async processing", interview.id)
        interview.status = "report_processing"
        await db.commit()
        _schedule_report_generation(interview.id)
        return FinishInterviewResponse(
            interview_id=interview.id,
            status="report_processing",
            report_id=None,
            summary=None,
        )

async def _ensure_report_generated(
    db: AsyncSession,
    interview: Interview,
    candidate: Candidate,
) -> AssessmentReport:
    existing_report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )
    if existing_report:
        if interview.status != "report_generated":
            interview.status = "report_generated"
            await db.commit()
        return existing_report

    messages = await _get_messages(db, interview.id)
    result: AssessmentResult = await assessor.assess(
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
    await db.commit()
    await db.refresh(report)

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
        return
    _REPORT_GENERATION_TASKS.add(interview_id)
    asyncio.create_task(_run_report_generation_job(interview_id))


async def _run_report_generation_job(interview_id: uuid.UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            interview = await session.scalar(select(Interview).where(Interview.id == interview_id))
            if not interview:
                return

            existing_report = await session.scalar(
                select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
            )
            if existing_report:
                if interview.status != "report_generated":
                    interview.status = "report_generated"
                    await session.commit()
                return

            candidate = await session.scalar(select(Candidate).where(Candidate.id == interview.candidate_id))
            if not candidate:
                interview.status = "failed"
                await session.commit()
                return

            interview.status = "report_processing"
            await session.commit()
            await _ensure_report_generated(session, interview, candidate)
    except Exception:
        logger.exception("Async report generation failed for interview %s", interview_id)
        async with AsyncSessionLocal() as session:
            interview = await session.scalar(select(Interview).where(Interview.id == interview_id))
            if interview and interview.status != "report_generated":
                interview.status = "failed"
                await session.commit()
    finally:
        _REPORT_GENERATION_TASKS.discard(interview_id)


async def get_interview_report_status(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> InterviewReportStatusResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
    report = await db.scalar(
        select(AssessmentReport).where(AssessmentReport.interview_id == interview.id)
    )

    if report:
        if interview.status != "report_generated":
            interview.status = "report_generated"
            await db.commit()
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
        )

    if interview.status == "failed":
        state = "failed"
    elif interview.status in {"completed", "report_processing"}:
        state = "processing"
    else:
        state = "pending"

    if state == "processing":
        _schedule_report_generation(interview.id)

    return InterviewReportStatusResponse(
        interview_id=interview.id,
        status=interview.status,
        processing_state=state,
        report_id=None,
        summary=None,
    )


async def get_interview_detail(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> InterviewDetailResponse:
    interview = await _get_interview(db, interview_id, candidate.id)
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
    interview.behavioral_signals = normalize_behavioral_signals(signals)
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
        events=payload["events"],
    )


async def get_interview_replay(
    db: AsyncSession,
    interview_id: uuid.UUID,
    company_id: uuid.UUID,
) -> InterviewReplayResponse | None:
    """Return a Q&A replay annotated with per-question analysis."""
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

    turns: list[ReplayTurn] = []
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
            turns.append(ReplayTurn(
                question_number=q_num,
                question=question_msg.content,
                answer=answer_msg.content if answer_msg else "",
                question_time=question_msg.created_at,
                answer_time=answer_msg.created_at if answer_msg else None,
                analysis=analysis,
            ))
            i += 2 if answer_msg else 1
        else:
            i += 1

    return InterviewReplayResponse(
        interview_id=interview.id,
        candidate_id=interview.candidate_id,
        candidate_name=candidate_name,
        target_role=interview.target_role,
        completed_at=interview.completed_at,
        turns=turns,
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
