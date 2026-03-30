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
        language=language,
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
        language=language,
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
            language=interview.language,
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
            behavioral_signals=interview.behavioral_signals,
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
