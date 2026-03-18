import uuid
from collections import defaultdict
from datetime import datetime
from statistics import median

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, PROFILE_VISIBILITY_MARKETPLACE
from app.models.company_assessment import CompanyAssessment
from app.models.hire_outcome import HireOutcome
from app.models.interview import Interview
from app.models.report import AssessmentReport
from app.models.skill import CandidateSkill
from app.models.template import InterviewTemplate
from app.models.user import User
from app.schemas.company import (
    AnalyticsBreakdownItemResponse,
    AnalyticsFunnelResponse,
    AnalyticsFunnelRowResponse,
    AnalyticsOverviewResponse,
    AnalyticsRedFlagSummaryResponse,
    AnalyticsSalaryBandResponse,
    AnalyticsSalaryBucketResponse,
    AnalyticsSalaryOutcomeTrendResponse,
    AnalyticsSalaryResponse,
    AnalyticsSalaryRoleResponse,
    AnalyticsTemplatePerformanceResponse,
    CandidateDetailResponse,
    CandidateListItemResponse,
    ReportWithRoleResponse,
)
from app.services.candidate_access_service import has_company_candidate_workspace_access
from app.services.shortlist_service import get_candidate_shortlists_map

_ROLE_LABELS = {
    "backend_engineer": "Backend Engineer",
    "frontend_engineer": "Frontend Engineer",
    "qa_engineer": "QA Engineer",
    "devops_engineer": "DevOps Engineer",
    "data_scientist": "Data Scientist",
    "product_manager": "Product Manager",
    "mobile_engineer": "Mobile Engineer",
    "designer": "UX/UI Designer",
}
_RECOMMENDATION_LABELS = {
    "strong_yes": "Strong Yes",
    "yes": "Yes",
    "maybe": "Maybe",
    "no": "No",
}
_PROFICIENCY_RANK = {
    "beginner": 0,
    "intermediate": 1,
    "advanced": 2,
    "expert": 3,
}


def _normalize_skill_name(value: str) -> str:
    return value.strip().lower()


def _is_marketplace_candidate(candidate: Candidate) -> bool:
    return candidate.profile_visibility == PROFILE_VISIBILITY_MARKETPLACE


def _score_bucket(score: float | None) -> str:
    if score is None or score <= 4:
        return "0-4"
    if score <= 6:
        return "5-6"
    if score <= 8:
        return "7-8"
    return "9-10"


def _median(values: list[int]) -> float | None:
    return float(median(values)) if values else None


def _build_salary_band(ranges: list[tuple[int, int]]) -> AnalyticsSalaryBandResponse:
    if not ranges:
        return AnalyticsSalaryBandResponse(candidate_count=0)

    lows = [low for low, _ in ranges]
    highs = [high for _, high in ranges]
    return AnalyticsSalaryBandResponse(
        candidate_count=len(ranges),
        range_min=float(min(lows)),
        median_min=_median(lows),
        median_max=_median(highs),
        range_max=float(max(highs)),
    )


def _salary_matches(
    candidate_min: int | None,
    candidate_max: int | None,
    filter_min: int | None,
    filter_max: int | None,
) -> bool:
    if filter_min is None and filter_max is None:
        return True
    if candidate_min is None and candidate_max is None:
        return False

    low = candidate_min if candidate_min is not None else candidate_max
    high = candidate_max if candidate_max is not None else candidate_min
    if low is None or high is None:
        return False

    if filter_min is not None and high < filter_min:
        return False
    if filter_max is not None and low > filter_max:
        return False
    return True


async def _load_candidate_skills_map(
    db: AsyncSession,
    candidate_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, set[str]], dict[uuid.UUID, list[dict]]]:
    if not candidate_ids:
        return {}, {}

    result = await db.execute(
        select(CandidateSkill)
        .where(CandidateSkill.candidate_id.in_(candidate_ids))
        .order_by(CandidateSkill.created_at.desc())
    )

    normalized_skills: dict[uuid.UUID, dict[str, dict]] = defaultdict(dict)
    for skill in result.scalars().all():
        skill_name = _normalize_skill_name(skill.skill_name)
        existing = normalized_skills[skill.candidate_id].get(skill_name)
        candidate_entry = {
            "skill": skill.skill_name,
            "proficiency": skill.proficiency,
            "mentions_count": 1,
        }
        if existing is None or _PROFICIENCY_RANK.get(skill.proficiency, 0) > _PROFICIENCY_RANK.get(existing["proficiency"], 0):
            normalized_skills[skill.candidate_id][skill_name] = candidate_entry

    names_map = {
        candidate_id: set(skill_map.keys())
        for candidate_id, skill_map in normalized_skills.items()
    }
    tags_map = {
        candidate_id: sorted(
            skill_map.values(),
            key=lambda item: (-_PROFICIENCY_RANK.get(item["proficiency"], 0), item["skill"].lower()),
        )
        for candidate_id, skill_map in normalized_skills.items()
    }
    return names_map, tags_map


async def _load_marketplace_snapshot(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> list[CandidateListItemResponse]:
    result = await db.execute(
        select(AssessmentReport, Interview, Candidate, User)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .join(Candidate, AssessmentReport.candidate_id == Candidate.id)
        .join(User, Candidate.user_id == User.id)
        .where(
            Interview.company_assessment_id.is_(None),
            Candidate.profile_visibility == PROFILE_VISIBILITY_MARKETPLACE,
        )
        .order_by(desc(AssessmentReport.created_at))
    )
    rows = result.all()

    latest_rows: list[tuple[AssessmentReport, Interview, Candidate, User]] = []
    seen: set[uuid.UUID] = set()
    for report, interview, candidate, user in rows:
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        latest_rows.append((report, interview, candidate, user))

    candidate_ids = [candidate.id for _, _, candidate, _ in latest_rows]
    outcome_map: dict[uuid.UUID, str] = {}
    if candidate_ids:
        outcomes = await db.scalars(
            select(HireOutcome).where(
                HireOutcome.company_id == company_id,
                HireOutcome.candidate_id.in_(candidate_ids),
            )
        )
        for outcome in outcomes:
            outcome_map[outcome.candidate_id] = outcome.outcome

    shortlist_map = await get_candidate_shortlists_map(db, company_id, candidate_ids)
    skill_name_map, aggregated_skill_tags_map = await _load_candidate_skills_map(db, candidate_ids)

    items: list[CandidateListItemResponse] = []
    for report, interview, candidate, user in latest_rows:
        report_skill_tags = report.skill_tags or aggregated_skill_tags_map.get(candidate.id) or []
        normalized_skill_names = skill_name_map.get(candidate.id)
        if normalized_skill_names is None:
            normalized_skill_names = {
                _normalize_skill_name(tag.get("skill", ""))
                for tag in report_skill_tags
                if tag.get("skill")
            }

        items.append(
            CandidateListItemResponse(
                candidate_id=candidate.id,
                full_name=candidate.full_name,
                email=user.email,
                target_role=interview.target_role,
                overall_score=report.overall_score,
                hiring_recommendation=report.hiring_recommendation,
                interview_summary=report.interview_summary,
                report_id=report.id,
                completed_at=interview.completed_at,
                salary_min=candidate.salary_min,
                salary_max=candidate.salary_max,
                salary_currency=candidate.salary_currency,
                hire_outcome=outcome_map.get(candidate.id),
                skill_tags=report_skill_tags[:6],
                shortlists=shortlist_map.get(candidate.id, []),
                cheat_risk_score=report.cheat_risk_score,
                red_flag_count=len(report.red_flags or []),
            )
        )

    return items


def _apply_candidate_filters(
    items: list[CandidateListItemResponse],
    *,
    q: str | None = None,
    role: str | None = None,
    skills: list[str] | None = None,
    min_score: float | None = None,
    recommendation: str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    hire_outcome: str | None = None,
    shortlist_id: uuid.UUID | None = None,
    sort: str = "score_desc",
) -> list[CandidateListItemResponse]:
    filtered = items

    if q:
        needle = q.strip().lower()
        filtered = [
            item for item in filtered
            if needle in item.full_name.lower() or needle in item.email.lower()
        ]

    if role:
        filtered = [item for item in filtered if item.target_role == role]

    if recommendation:
        filtered = [item for item in filtered if item.hiring_recommendation == recommendation]

    if min_score is not None:
        filtered = [item for item in filtered if item.overall_score is not None and item.overall_score >= min_score]

    if hire_outcome:
        filtered = [item for item in filtered if item.hire_outcome == hire_outcome]

    if shortlist_id:
        shortlist_str = str(shortlist_id)
        filtered = [
            item for item in filtered
            if any(str(m.shortlist_id) == shortlist_str for m in item.shortlists)
        ]

    if skills:
        required_skills = {
            _normalize_skill_name(skill)
            for skill in skills
            if skill.strip()
        }
        if required_skills:
            filtered = [
                item
                for item in filtered
                if required_skills.issubset(
                    {
                        _normalize_skill_name(tag.get("skill", ""))
                        for tag in (item.skill_tags or [])
                        if tag.get("skill")
                    }
                )
            ]

    if salary_min is not None or salary_max is not None:
        filtered = [
            item for item in filtered
            if _salary_matches(item.salary_min, item.salary_max, salary_min, salary_max)
        ]

    if sort == "latest":
        filtered = sorted(filtered, key=lambda item: item.completed_at or datetime.min, reverse=True)
    elif sort == "score_asc":
        filtered = sorted(filtered, key=lambda item: (item.overall_score is None, item.overall_score or 0))
    elif sort == "salary_asc":
        filtered = sorted(filtered, key=lambda item: (item.salary_min is None and item.salary_max is None, item.salary_min or item.salary_max or 0))
    elif sort == "salary_desc":
        filtered = sorted(filtered, key=lambda item: item.salary_max or item.salary_min or -1, reverse=True)
    else:
        filtered = sorted(filtered, key=lambda item: item.overall_score or -1, reverse=True)

    return filtered


async def list_verified_candidates(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    q: str | None = None,
    role: str | None = None,
    skills: list[str] | None = None,
    min_score: float | None = None,
    recommendation: str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    hire_outcome: str | None = None,
    shortlist_id: uuid.UUID | None = None,
    sort: str = "score_desc",
) -> list[CandidateListItemResponse]:
    items = await _load_marketplace_snapshot(db, company_id)
    return _apply_candidate_filters(
        items,
        q=q,
        role=role,
        skills=skills,
        min_score=min_score,
        recommendation=recommendation,
        salary_min=salary_min,
        salary_max=salary_max,
        hire_outcome=hire_outcome,
        shortlist_id=shortlist_id,
        sort=sort,
    )


async def get_candidate_detail(
    db: AsyncSession,
    candidate_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
) -> CandidateDetailResponse | None:
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        return None
    if company_id is not None and not await has_company_candidate_workspace_access(db, company_id, candidate):
        return None

    user = await db.scalar(select(User).where(User.id == candidate.user_id))
    if not user:
        return None

    result = await db.execute(
        select(AssessmentReport, Interview)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .where(
            AssessmentReport.candidate_id == candidate_id,
            Interview.company_assessment_id.is_(None),
        )
        .order_by(desc(AssessmentReport.created_at))
    )
    rows = result.all()
    if not rows:
        return None

    hire_outcome = None
    hire_notes = None
    shortlists = []
    if company_id:
        ho = await db.scalar(
            select(HireOutcome).where(
                HireOutcome.company_id == company_id,
                HireOutcome.candidate_id == candidate_id,
            )
        )
        if ho:
            hire_outcome = ho.outcome
            hire_notes = ho.notes
        shortlists_map = await get_candidate_shortlists_map(db, company_id, [candidate_id])
        shortlists = shortlists_map.get(candidate_id, [])

    reports = [
        ReportWithRoleResponse(
            report_id=report.id,
            interview_id=report.interview_id,
            target_role=interview.target_role,
            overall_score=report.overall_score,
            hard_skills_score=report.hard_skills_score,
            soft_skills_score=report.soft_skills_score,
            communication_score=report.communication_score,
            problem_solving_score=report.problem_solving_score,
            strengths=report.strengths,
            weaknesses=report.weaknesses,
            recommendations=report.recommendations,
            hiring_recommendation=report.hiring_recommendation,
            interview_summary=report.interview_summary,
            created_at=report.created_at,
            competency_scores=report.competency_scores,
            skill_tags=report.skill_tags,
            red_flags=report.red_flags,
            response_consistency=report.response_consistency,
        )
        for report, interview in rows
    ]

    return CandidateDetailResponse(
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        email=user.email,
        salary_min=candidate.salary_min,
        salary_max=candidate.salary_max,
        salary_currency=candidate.salary_currency,
        hire_outcome=hire_outcome,
        hire_notes=hire_notes,
        shortlists=shortlists,
        reports=reports,
    )


async def get_company_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    company_id: uuid.UUID,
) -> AssessmentReport | None:
    result = await db.execute(
        select(AssessmentReport, Interview)
        .join(Interview, AssessmentReport.interview_id == Interview.id)
        .where(AssessmentReport.id == report_id)
    )
    row = result.first()
    if not row:
        return None

    report, interview = row
    if interview.company_assessment_id is None:
        candidate = await db.scalar(select(Candidate).where(Candidate.id == report.candidate_id))
        if not candidate or not await has_company_candidate_workspace_access(db, company_id, candidate):
            return None
        return report

    assessment = await db.scalar(
        select(CompanyAssessment).where(CompanyAssessment.id == interview.company_assessment_id)
    )
    if not assessment or assessment.company_id != company_id:
        return None

    return report


async def get_analytics_overview(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> AnalyticsOverviewResponse:
    items = await _load_marketplace_snapshot(db, company_id)

    role_counts: dict[str, int] = defaultdict(int)
    recommendation_counts: dict[str, int] = defaultdict(int)
    cheat_risk_counts = {"low": 0, "medium": 0, "high": 0}
    shortlisted_candidates = 0
    candidates_with_flags = 0
    total_flags = 0

    for item in items:
        role_counts[item.target_role] += 1
        recommendation_counts[item.hiring_recommendation] += 1
        if item.shortlists:
            shortlisted_candidates += 1
        if item.red_flag_count > 0:
            candidates_with_flags += 1
            total_flags += item.red_flag_count
        if item.cheat_risk_score is not None:
            if item.cheat_risk_score >= 0.7:
                cheat_risk_counts["high"] += 1
            elif item.cheat_risk_score >= 0.4:
                cheat_risk_counts["medium"] += 1
            else:
                cheat_risk_counts["low"] += 1

    template_rows = await db.execute(
        select(InterviewTemplate.id, InterviewTemplate.name, Interview.target_role, AssessmentReport.overall_score)
        .join(Interview, Interview.template_id == InterviewTemplate.id)
        .join(AssessmentReport, AssessmentReport.interview_id == Interview.id)
        .where(
            Interview.company_assessment_id.is_(None),
            InterviewTemplate.company_id == company_id,
        )
    )

    template_stats: dict[uuid.UUID, dict] = {}
    for template_id, template_name, target_role, overall_score in template_rows.all():
        stats = template_stats.setdefault(
            template_id,
            {
                "template_name": template_name,
                "target_role": target_role,
                "scores": [],
            },
        )
        if overall_score is not None:
            stats["scores"].append(overall_score)

    template_performance = [
        AnalyticsTemplatePerformanceResponse(
            template_id=template_id,
            template_name=stats["template_name"],
            target_role=stats["target_role"],
            completed_count=len(stats["scores"]),
            average_score=round(sum(stats["scores"]) / len(stats["scores"]), 2) if stats["scores"] else None,
        )
        for template_id, stats in sorted(
            template_stats.items(),
            key=lambda item: len(item[1]["scores"]),
            reverse=True,
        )
    ]

    return AnalyticsOverviewResponse(
        total_candidates=len(items),
        total_reports=len(items),
        shortlisted_candidates=shortlisted_candidates,
        role_breakdown=[
            AnalyticsBreakdownItemResponse(
                key=role,
                label=_ROLE_LABELS.get(role, role),
                count=count,
            )
            for role, count in sorted(role_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        recommendation_breakdown=[
            AnalyticsBreakdownItemResponse(
                key=rec,
                label=_RECOMMENDATION_LABELS.get(rec, rec),
                count=count,
            )
            for rec, count in sorted(recommendation_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        cheat_risk_breakdown=[
            AnalyticsBreakdownItemResponse(key=bucket, label=bucket.title(), count=count)
            for bucket, count in cheat_risk_counts.items()
        ],
        red_flag_summary=AnalyticsRedFlagSummaryResponse(
            candidates_with_flags=candidates_with_flags,
            total_flags=total_flags,
        ),
        template_performance=template_performance,
    )


async def get_analytics_funnel(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> AnalyticsFunnelResponse:
    items = await _load_marketplace_snapshot(db, company_id)

    buckets: dict[str, dict[str, int]] = {
        rec: {
            "total": 0,
            "unreviewed": 0,
            "interviewing": 0,
            "hired": 0,
            "rejected": 0,
            "no_show": 0,
        }
        for rec in ("strong_yes", "yes", "maybe", "no")
    }

    for item in items:
        stats = buckets.setdefault(item.hiring_recommendation, {
            "total": 0,
            "unreviewed": 0,
            "interviewing": 0,
            "hired": 0,
            "rejected": 0,
            "no_show": 0,
        })
        stats["total"] += 1
        outcome = item.hire_outcome or "unreviewed"
        stats[outcome] = stats.get(outcome, 0) + 1

    return AnalyticsFunnelResponse(
        rows=[
            AnalyticsFunnelRowResponse(
                recommendation=rec,
                total=stats["total"],
                unreviewed=stats["unreviewed"],
                interviewing=stats["interviewing"],
                hired=stats["hired"],
                rejected=stats["rejected"],
                no_show=stats["no_show"],
            )
            for rec, stats in buckets.items()
        ]
    )


async def get_salary_analytics(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    role: str | None = None,
    shortlist_id: uuid.UUID | None = None,
) -> AnalyticsSalaryResponse:
    items = await list_verified_candidates(
        db,
        company_id=company_id,
        role=role,
        shortlist_id=shortlist_id,
        sort="score_desc",
    )

    grouped: dict[tuple[str, str], list[CandidateListItemResponse]] = defaultdict(list)
    for item in items:
        if item.salary_min is None and item.salary_max is None:
            continue
        grouped[(item.target_role, item.salary_currency or "USD")].append(item)

    roles: list[AnalyticsSalaryRoleResponse] = []
    for (target_role, currency), role_items in sorted(
        grouped.items(),
        key=lambda item: (_ROLE_LABELS.get(item[0][0], item[0][0]), item[0][1]),
    ):
        buckets_data: dict[str, list[tuple[int, int]]] = defaultdict(list)
        outcome_data: dict[str, list[tuple[int, int]]] = defaultdict(list)
        all_ranges: list[tuple[int, int]] = []
        shortlisted_ranges: list[tuple[int, int]] = []

        for item in role_items:
            low = item.salary_min if item.salary_min is not None else item.salary_max
            high = item.salary_max if item.salary_max is not None else item.salary_min
            if low is None or high is None:
                continue
            all_ranges.append((low, high))
            if item.shortlists:
                shortlisted_ranges.append((low, high))
            buckets_data[_score_bucket(item.overall_score)].append((low, high))
            outcome_data[item.hire_outcome or "unreviewed"].append((low, high))

        buckets = []
        for bucket in ("0-4", "5-6", "7-8", "9-10"):
            ranges = buckets_data.get(bucket, [])
            buckets.append(
                AnalyticsSalaryBucketResponse(
                    score_range=bucket,
                    median_min=_median([low for low, _ in ranges]),
                    median_max=_median([high for _, high in ranges]),
                    count=len(ranges),
                )
            )

        outcome_trends = [
            AnalyticsSalaryOutcomeTrendResponse(
                outcome=outcome,
                median_min=_median([low for low, _ in ranges]),
                median_max=_median([high for _, high in ranges]),
                count=len(ranges),
            )
            for outcome, ranges in sorted(outcome_data.items(), key=lambda item: item[0])
        ]

        roles.append(
            AnalyticsSalaryRoleResponse(
                role=target_role,
                currency=currency,
                candidate_count=len(role_items),
                market_band=_build_salary_band(all_ranges),
                shortlisted_band=_build_salary_band(shortlisted_ranges) if shortlisted_ranges else None,
                buckets=buckets,
                outcome_trends=outcome_trends,
            )
        )

    return AnalyticsSalaryResponse(
        role=role,
        shortlist_id=shortlist_id,
        roles=roles,
    )
