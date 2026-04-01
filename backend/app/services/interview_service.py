"""
Interview service — owns all interview business logic.
Routers call these functions; no SQLAlchemy queries in routers.

question_count is an explicit DB column on Interview, incremented here.
It is the authoritative source of truth — no need to re-count messages.
"""
import uuid
from datetime import datetime
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assessor import AssessmentResult, assessor
from app.ai.competencies import build_interview_plan
from app.ai.interviewer import (
    MAX_QUESTIONS,
    InterviewContext,
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
    InterviewMessageResponse,
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
        elif closed_reason in {"reused_answer", "low_relevance_after_probe"}:
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
        elif closed_reason in {"reused_answer", "low_relevance_after_probe"}:
            parts.append("Задай вопрос с явно другого угла, чтобы кандидат не мог повторить прежний ответ.")
    return " ".join(parts) if parts else None


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

    max_q = len(template.questions) if template else MAX_QUESTIONS

    resume_profile = preprocess_resume(active_resume.raw_text, target_role)
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
    )
    first_question = await interviewer.get_next_question(ctx)

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
        current_question_text = history[-1]["content"] if history else None
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
            answer_class = "generic"
            shallow_reason = "low_relevance"
        elif answer_class == "strong" and answer_relevance == "medium":
            answer_class = "partial"
        if answer_relevance == "low":
            topic_relevance_failures[current_topic_index] += 1

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

        ranked_claim_target = _rank_verification_target(
            current_claim_target=claim_target,
            new_techs=new_techs,
            current_question=current_question_text,
            verified_skills=verified_skills,
            probed_claim_targets=probed_claim_targets,
        )

        if force_topic_closure:
            question_type = "main"
            will_advance = True
        elif topic_saturated:
            question_type = "main"
            will_advance = True

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

        competency_targets = None
        resume_anchor = None
        verification_target = None
        diversification_hint = None
        if topic_plan:
            current_idx = max(current_topic_index, 0)
            next_idx = interview.question_count
            target_idx = next_idx if will_advance else current_idx
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

        # ── Build InterviewContext ──────────────────────────────────────────
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
        )
        next_q = await interviewer.get_next_question(ctx)

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

        if will_advance:
            topic_closed_reasons[current_topic_index] = forced_closure_reason or saturation_reason or "advanced"
            topic_mastered_flags[current_topic_index] = bool(saturation_reason in {"topic_mastered", "topic_saturated"})
            interview.question_count += 1
            interview.followup_depth = 0
            topic_turns = 0
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
        }

        db.add(InterviewMessage(
            id=uuid.uuid4(),
            interview_id=interview.id,
            role="assistant",
            content=next_q,
        ))
        current_question = next_q

    await db.commit()
    await db.refresh(interview)

    return SendMessageResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        current_question=current_question,
        is_followup=not will_advance,
        question_type=question_type,
    )


async def finish_interview(
    db: AsyncSession,
    candidate: Candidate,
    interview_id: uuid.UUID,
) -> FinishInterviewResponse:
    interview = await _get_interview(db, interview_id, candidate.id)

    if interview.status == "report_generated":
        raise InterviewAlreadyFinishedError()
    if interview.status != "in_progress":
        raise InterviewNotActiveError()

    if interview.question_count < interview.max_questions:
        raise MaxQuestionsNotReachedError()

    messages = await _get_messages(db, interview.id)

    # Phase 1: mark completed
    interview.status = "completed"
    interview.completed_at = datetime.utcnow()
    await db.commit()

    # Phase 2: generate report — failure marks status=failed, "completed" rows
    # can be retried by a background job later.
    try:
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

        # Persist extracted skills to candidate_skills table
        if result.skill_tags:
            _save_skills(db, interview.candidate_id, report.id, result.skill_tags)

        interview.status = "report_generated"
        await db.commit()
        await db.refresh(report)

        # Sync company assessment status if this was an employee assessment
        if interview.company_assessment_id:
            from app.services.assessment_invite_service import sync_assessment_status
            await sync_assessment_status(db, interview.id)

        # Send email notifications (fire-and-forget, never crash the response)
        try:
            from app.models.user import User
            from app.core.config import settings
            from app.services.email_service import send_report_ready, send_new_candidate_to_company

            user = await db.scalar(select(User).where(User.id == candidate.user_id))
            role_label = interview.target_role.replace("_", " ").title()

            # 1. Notify candidate
            if user:
                await send_report_ready(
                    candidate_email=user.email,
                    candidate_name=candidate.full_name,
                    role=role_label,
                    overall_score=report.overall_score or 0,
                    report_id=str(report.id),
                    app_url=settings.APP_URL,
                )

            # 2. Notify the owning company only for private employee assessments.
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
        except Exception as _email_exc:
            import logging
            logging.getLogger(__name__).warning("Email notification failed: %s", _email_exc)

    except Exception:
        interview.status = "failed"
        await db.commit()
        raise

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
    interview.behavioral_signals = signals
    await db.commit()


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
