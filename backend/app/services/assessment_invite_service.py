"""
Company assessment invite service.

Handles creation, listing, and linking of company-owned private assessment campaigns.
"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.company_assessment import CompanyAssessment
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.template import InterviewTemplate
from app.services.company_settings_service import get_company_ai_settings_response

_ACTIVE_INVITE_STATUSES = {"pending", "opened"}
_DEFAULT_ASSESSMENT_MODULE_TYPE = "adaptive_interview"
_INTERVIEW_FLOW_MODULE_TYPES = {
    _DEFAULT_ASSESSMENT_MODULE_TYPE,
    "system_design",
    "coding_task",
    "sql_live",
}
_ASSESSMENT_MODULE_TITLE_MAP = {
    "adaptive_interview": "Adaptive Interview",
    "system_design": "System Design",
    "coding_task": "Coding Task",
    "behavioral_interview": "Behavioral Interview",
    "written_communication": "Written Communication",
    "sql_live": "SQL Live",
    "data_analysis": "Data Analysis",
    "devops_incident": "DevOps Incident",
}
_ASSESSMENT_MODULE_STATUSES = {"pending", "in_progress", "completed", "blocked"}


def _module_title(module_type: str) -> str:
    return _ASSESSMENT_MODULE_TITLE_MAP.get(
        module_type,
        module_type.replace("_", " ").strip().title() or "Assessment Module",
    )


def _build_default_module_plan(
    *,
    target_role: str,
    template_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    return [
        {
            "module_id": "adaptive_interview_1",
            "module_type": _DEFAULT_ASSESSMENT_MODULE_TYPE,
            "title": _module_title(_DEFAULT_ASSESSMENT_MODULE_TYPE),
            "status": "pending",
            "config": {
                "target_role": target_role,
                "template_id": str(template_id) if template_id else None,
            },
            "interview_id": None,
            "started_at": None,
            "completed_at": None,
        }
    ]


def normalize_assessment_module_plan(
    module_plan: list[dict[str, Any]] | None,
    *,
    target_role: str,
    template_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    raw_plan = module_plan if isinstance(module_plan, list) and module_plan else _build_default_module_plan(
        target_role=target_role,
        template_id=template_id,
    )

    normalized: list[dict[str, Any]] = []
    for idx, raw_module in enumerate(raw_plan):
        item = raw_module if isinstance(raw_module, dict) else {}
        module_type = str(item.get("module_type") or item.get("type") or _DEFAULT_ASSESSMENT_MODULE_TYPE).strip().lower()
        title = str(item.get("title") or _module_title(module_type)).strip() or _module_title(module_type)
        status_value = str(item.get("status") or "pending").strip().lower()
        status_label = status_value if status_value in _ASSESSMENT_MODULE_STATUSES else "pending"
        config = item.get("config") if isinstance(item.get("config"), dict) else {}
        interview_id = item.get("interview_id")
        started_at = item.get("started_at")
        completed_at = item.get("completed_at")
        normalized.append(
            {
                "module_id": str(item.get("module_id") or f"{module_type}_{idx + 1}"),
                "module_type": module_type,
                "title": title,
                "status": status_label,
                "config": config,
                "interview_id": str(interview_id) if interview_id else None,
                "started_at": str(started_at) if started_at else None,
                "completed_at": str(completed_at) if completed_at else None,
            }
        )

    return normalized


def prepare_assessment_module_plan(
    module_plan: list[dict[str, Any]] | None,
    *,
    target_role: str,
    template_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    if module_plan is not None and not module_plan:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="module_plan must contain at least one module",
        )

    normalized = normalize_assessment_module_plan(
        module_plan,
        target_role=target_role,
        template_id=template_id,
    )
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="module_plan must contain at least one module",
        )

    seen_module_ids: set[str] = set()
    prepared: list[dict[str, Any]] = []
    for item in normalized:
        module_type = item["module_type"]
        module_id = item["module_id"]
        if module_type not in _ASSESSMENT_MODULE_TITLE_MAP:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported module_type '{module_type}'",
            )
        if module_id in seen_module_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate module_id '{module_id}' in module_plan",
            )

        seen_module_ids.add(module_id)
        config = dict(item.get("config") or {})
        config.setdefault("target_role", target_role)
        if module_type == _DEFAULT_ASSESSMENT_MODULE_TYPE:
            config["template_id"] = str(template_id) if template_id else None

        prepared.append(
            {
                "module_id": module_id,
                "module_type": module_type,
                "title": item["title"],
                "status": "pending",
                "config": config,
                "interview_id": None,
                "started_at": None,
                "completed_at": None,
            }
        )

    if prepared[0]["module_type"] != _DEFAULT_ASSESSMENT_MODULE_TYPE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="First module must be adaptive_interview until other start flows are implemented",
        )

    return prepared


def _normalized_module_index(assessment: CompanyAssessment, module_plan: list[dict[str, Any]]) -> int:
    if not module_plan:
        return 0
    try:
        current_idx = int(assessment.current_module_index)
    except (TypeError, ValueError):
        current_idx = 0
    return min(max(current_idx, 0), len(module_plan) - 1)


def get_current_assessment_module_payload(
    assessment: CompanyAssessment,
) -> tuple[list[dict[str, Any]], int, dict[str, Any] | None]:
    module_plan = normalize_assessment_module_plan(
        assessment.module_plan,
        target_role=assessment.target_role,
        template_id=assessment.template_id,
    )
    current_idx = _normalized_module_index(assessment, module_plan)
    current_module = module_plan[current_idx] if module_plan else None
    return module_plan, current_idx, current_module


def can_start_current_assessment_module_via_interview(
    assessment: CompanyAssessment,
    *,
    has_active_interview: bool = False,
) -> bool:
    _, _, current_module = get_current_assessment_module_payload(assessment)
    if not current_module:
        return False
    if has_active_interview:
        return False
    if assessment.status in {"completed", "expired"}:
        return False
    return (
        current_module.get("module_type") in _INTERVIEW_FLOW_MODULE_TYPES
        and current_module.get("status") == "pending"
    )


def build_assessment_progress_payload(
    assessment: CompanyAssessment,
    *,
    interview_id: uuid.UUID,
) -> dict[str, Any]:
    module_plan, current_module_index, current_module = get_current_assessment_module_payload(assessment)
    return {
        "assessment_id": assessment.id,
        "invite_token": assessment.invite_token,
        "assessment_status": assessment.status,
        "has_remaining_modules": assessment.status != "completed" and assessment.interview_id != interview_id,
        "module_count": len(module_plan),
        "current_module_index": current_module_index,
        "current_module_type": current_module.get("module_type") if current_module else None,
        "current_module_title": current_module.get("title") if current_module else None,
    }


def mark_current_assessment_module_started(
    assessment: CompanyAssessment,
    *,
    interview_id: uuid.UUID,
    started_at: datetime | None = None,
) -> None:
    module_plan, current_idx, current_module = get_current_assessment_module_payload(assessment)
    if not current_module:
        return
    current_module["status"] = "in_progress"
    current_module["interview_id"] = str(interview_id)
    current_module["started_at"] = (started_at or datetime.utcnow()).isoformat()
    current_module["completed_at"] = None
    module_plan[current_idx] = current_module
    assessment.module_plan = module_plan
    assessment.current_module_index = current_idx


def sync_assessment_module_progress(
    assessment: CompanyAssessment,
    *,
    completed_interview_id: uuid.UUID,
    completed_at: datetime | None = None,
) -> bool:
    module_plan, current_idx, current_module = get_current_assessment_module_payload(assessment)
    if not current_module:
        return True

    current_module["status"] = "completed"
    current_module["interview_id"] = str(completed_interview_id)
    current_module["completed_at"] = (completed_at or datetime.utcnow()).isoformat()
    module_plan[current_idx] = current_module

    next_idx = current_idx + 1
    if next_idx < len(module_plan):
        assessment.current_module_index = next_idx
        assessment.module_plan = module_plan
        return False

    assessment.current_module_index = current_idx
    assessment.module_plan = module_plan
    return True


def _is_past_due(assessment: CompanyAssessment, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if assessment.expires_at and now >= assessment.expires_at:
        return True
    if assessment.deadline_at and now >= assessment.deadline_at:
        return True
    return False


async def _refresh_assessment_status(
    db: AsyncSession,
    assessment: CompanyAssessment,
    *,
    now: datetime | None = None,
) -> CompanyAssessment:
    if assessment.status in _ACTIVE_INVITE_STATUSES and _is_past_due(assessment, now):
        assessment.status = "expired"
        await db.commit()
    return assessment


async def _serialize_assessment_rows(
    db: AsyncSession,
    assessments: list[CompanyAssessment],
) -> list[dict]:
    assessments = [await _refresh_assessment_status(db, assessment) for assessment in assessments]
    interview_ids = [assessment.interview_id for assessment in assessments if assessment.interview_id]
    report_map: dict[uuid.UUID, str] = {}
    if interview_ids:
        reports = await db.execute(
            select(AssessmentReport).where(AssessmentReport.interview_id.in_(interview_ids))
        )
        for report in reports.scalars().all():
            report_map[report.interview_id] = str(report.id)

    rows: list[dict] = []
    for assessment in assessments:
        module_plan, current_module_index, current_module = get_current_assessment_module_payload(assessment)
        rows.append(
            {
                "id": str(assessment.id),
                "employee_email": assessment.employee_email,
                "employee_name": assessment.employee_name,
                "assessment_type": assessment.assessment_type,
                "target_role": assessment.target_role,
                "template_id": str(assessment.template_id) if assessment.template_id else None,
                "template_name": assessment.template.name if assessment.template else None,
                "status": assessment.status,
                "invite_token": assessment.invite_token,
                "interview_id": str(assessment.interview_id) if assessment.interview_id else None,
                "report_id": report_map.get(assessment.interview_id) if assessment.interview_id else None,
                "deadline_at": assessment.deadline_at.isoformat() if assessment.deadline_at else None,
                "expires_at": assessment.expires_at.isoformat() if assessment.expires_at else None,
                "opened_at": assessment.opened_at.isoformat() if assessment.opened_at else None,
                "completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
                "branding_name": assessment.branding_name,
                "branding_logo_url": assessment.branding_logo_url,
                "module_plan": module_plan,
                "module_count": len(module_plan),
                "current_module_index": current_module_index,
                "current_module_type": current_module.get("module_type") if current_module else None,
                "created_at": assessment.created_at.isoformat(),
            }
        )
    return rows


async def create_assessment(
    db: AsyncSession,
    company_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    employee_email: str,
    employee_name: str,
    target_role: str,
    *,
    assessment_type: str = "employee_internal",
    template_id: uuid.UUID | None = None,
    module_plan: list[dict[str, Any]] | None = None,
    deadline_at: datetime | None = None,
    expires_at: datetime | None = None,
    branding_name: str | None = None,
    branding_logo_url: str | None = None,
) -> CompanyAssessment:
    if assessment_type not in {"employee_internal", "candidate_external"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid assessment type")
    if deadline_at and expires_at and deadline_at > expires_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="deadline_at must be earlier than or equal to expires_at",
        )

    template: InterviewTemplate | None = None
    if template_id:
        template = await db.scalar(
            select(InterviewTemplate).where(InterviewTemplate.id == template_id)
        )
        if not template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        if template.company_id != company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your template")
        if template.target_role != target_role:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Template role does not match assessment target_role",
            )

    prepared_module_plan = prepare_assessment_module_plan(
        module_plan,
        target_role=target_role,
        template_id=template_id,
    )

    assessment = CompanyAssessment(
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        employee_email=employee_email.strip().lower(),
        employee_name=employee_name.strip(),
        assessment_type=assessment_type,
        target_role=target_role,
        template_id=template_id,
        deadline_at=deadline_at,
        expires_at=expires_at,
        branding_name=branding_name.strip() if branding_name else None,
        branding_logo_url=branding_logo_url.strip() if branding_logo_url else None,
        module_plan=prepared_module_plan,
        current_module_index=0,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    if template is not None:
        assessment.template = template
    return assessment


async def get_assessment_by_token(
    db: AsyncSession,
    token: str,
) -> CompanyAssessment | None:
    assessment = await db.scalar(
        select(CompanyAssessment)
        .options(
            selectinload(CompanyAssessment.company),
            selectinload(CompanyAssessment.template),
        )
        .where(CompanyAssessment.invite_token == token)
    )
    if assessment:
        await _refresh_assessment_status(db, assessment)
    return assessment


async def get_assessment_for_invite_view(
    db: AsyncSession,
    token: str,
) -> CompanyAssessment | None:
    assessment = await get_assessment_by_token(db, token)
    if not assessment:
        return None
    if assessment.status == "pending":
        assessment.status = "opened"
        assessment.opened_at = assessment.opened_at or datetime.utcnow()
        await db.commit()
    return assessment


async def list_company_assessments(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> list[dict]:
    result = await db.execute(
        select(CompanyAssessment)
        .options(selectinload(CompanyAssessment.template))
        .where(CompanyAssessment.company_id == company_id)
        .order_by(CompanyAssessment.created_at.desc())
    )
    assessments = list(result.scalars().all())
    return await _serialize_assessment_rows(db, assessments)


async def link_interview_to_assessment(
    db: AsyncSession,
    token: str,
    candidate: Candidate,
    candidate_email: str,
    target_role: str,
    language: str,
) -> tuple[CompanyAssessment, Interview]:
    """
    Called when an invitee starts an interview via invite link.
    Creates the interview and links it to the assessment.
    """
    from app.services.interview_service import start_interview

    assessment = await get_assessment_by_token(db, token)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if assessment.status == "expired":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This assessment invite has expired")
    if assessment.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This assessment has already been completed")
    if assessment.status == "in_progress" and assessment.interview_id:
        interview = await db.scalar(
            select(Interview).where(Interview.id == assessment.interview_id)
        )
        if interview and interview.status in {"created", "in_progress", "report_processing"}:
            return assessment, interview

    if assessment.target_role != target_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This invite is for role '{assessment.target_role}', not '{target_role}'",
        )

    if candidate_email.strip().lower() != assessment.employee_email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This assessment invite is assigned to a different email address",
        )

    _, _, current_module = get_current_assessment_module_payload(assessment)
    if current_module and current_module.get("module_type") not in _INTERVIEW_FLOW_MODULE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Current assessment module '{current_module.get('module_type')}' cannot be started via the interview flow yet",
        )

    module_type = str(current_module.get("module_type")) if current_module else _DEFAULT_ASSESSMENT_MODULE_TYPE
    module_title = str(current_module.get("title")) if current_module else _module_title(module_type)
    module_config = current_module.get("config") if current_module and isinstance(current_module.get("config"), dict) else {}
    template_id = assessment.template_id if module_type == _DEFAULT_ASSESSMENT_MODULE_TYPE else None
    workspace_ai_settings = get_company_ai_settings_response(assessment.company)

    start_response = await start_interview(
        db,
        candidate=candidate,
        target_role=target_role,
        template_id=template_id,
        language=language,
        module_type=module_type,
        module_title=module_title,
        module_config=module_config,
        workspace_ai_settings=workspace_ai_settings,
    )
    interview = await db.scalar(select(Interview).where(Interview.id == start_response.interview_id))
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Interview was created but could not be loaded",
        )

    interview.company_assessment_id = assessment.id
    assessment.interview_id = interview.id
    mark_current_assessment_module_started(
        assessment,
        interview_id=interview.id,
        started_at=interview.started_at or datetime.utcnow(),
    )
    assessment.status = "in_progress"
    assessment.opened_at = assessment.opened_at or datetime.utcnow()
    await db.commit()
    await db.refresh(assessment)
    await db.refresh(interview)

    return assessment, interview


async def sync_assessment_status(
    db: AsyncSession,
    interview_id: uuid.UUID,
) -> None:
    """Called after interview completes — updates assessment status to completed."""
    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.interview_id == interview_id)
    )
    if assessment and assessment.status == "in_progress":
        finished_at = datetime.utcnow()
        all_modules_completed = sync_assessment_module_progress(
            assessment,
            completed_interview_id=interview_id,
            completed_at=finished_at,
        )
        if all_modules_completed:
            assessment.status = "completed"
            assessment.completed_at = finished_at
            assessment.interview_id = interview_id
        else:
            assessment.interview_id = None
            assessment.completed_at = None
        await db.commit()


async def delete_assessment(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    company_id: uuid.UUID,
) -> None:
    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.id == assessment_id)
    )
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    if assessment.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your assessment")
    await db.delete(assessment)
    await db.commit()
