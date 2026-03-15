"""
Interview service — owns all interview business logic.
Routers call these functions; no SQLAlchemy queries in routers.

question_count is an explicit DB column on Interview, incremented here.
It is the authoritative source of truth — no need to re-count messages.
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assessor import AssessmentResult, assessor
from app.ai.competencies import build_question_plan
from app.ai.interviewer import MAX_QUESTIONS, InterviewContext, interviewer
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
    ReportSummary,
    SendMessageResponse,
    StartInterviewResponse,
)


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


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def start_interview(
    db: AsyncSession,
    candidate: Candidate,
    target_role: str,
    template_id: uuid.UUID | None = None,
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

    # Build competency question plan
    question_plan = build_question_plan(target_role, max_q)

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
        started_at=datetime.utcnow(),
    )
    db.add(interview)
    await db.flush()  # get interview.id

    # Store competency plan as system message for persistence
    import json
    plan_content = json.dumps({"competency_plan": question_plan}, ensure_ascii=False)
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
        competency_targets=question_plan[0] if question_plan else None,
    )
    first_question = await interviewer.get_next_question(ctx)

    db.add(InterviewMessage(
        id=uuid.uuid4(),
        interview_id=interview.id,
        role="assistant",
        content=first_question,
    ))

    # Explicitly set question_count = 1
    interview.question_count = 1
    interview.status = "in_progress"
    await db.commit()
    await db.refresh(interview)

    return StartInterviewResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        current_question=first_question,
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

        # Load competency plan from system message
        competency_targets = None
        import json
        for msg in messages:
            if msg.role == "system":
                try:
                    plan_data = json.loads(msg.content)
                    plan = plan_data.get("competency_plan", [])
                    q_idx = interview.question_count  # next question (0-based)
                    if q_idx < len(plan):
                        competency_targets = plan[q_idx]
                    break
                except (json.JSONDecodeError, KeyError):
                    pass

        resume = await db.scalar(select(Resume).where(Resume.id == interview.resume_id))
        ctx = InterviewContext(
            target_role=interview.target_role,
            question_number=interview.question_count + 1,
            max_questions=interview.max_questions,
            message_history=history,
            resume_text=resume.raw_text if resume else None,
            template_questions=template_questions,
            competency_targets=competency_targets,
        )
        next_q = await interviewer.get_next_question(ctx)

        db.add(InterviewMessage(
            id=uuid.uuid4(),
            interview_id=interview.id,
            role="assistant",
            content=next_q,
        ))
        # Explicitly increment question_count in DB
        interview.question_count += 1
        current_question = next_q

    await db.commit()
    await db.refresh(interview)

    return SendMessageResponse(
        interview_id=interview.id,
        status="in_progress",
        question_count=interview.question_count,
        max_questions=interview.max_questions,
        current_question=current_question,
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
        )
        db.add(report)
        await db.flush()

        # Persist extracted skills to candidate_skills table
        if result.skill_tags:
            _save_skills(db, interview.candidate_id, report.id, result.skill_tags)

        interview.status = "report_generated"
        await db.commit()
        await db.refresh(report)

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
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        messages=visible,
        has_report=report is not None,
        report_id=report.id if report else None,
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
