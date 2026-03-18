import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Register ──────────────────────────────────────────────────────────────────

class CompanyRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    company_name: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("company_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("company_name cannot be empty")
        return v.strip()


class CompanyRegisterResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    company_id: uuid.UUID
    company_name: str


class ShortlistMembershipResponse(BaseModel):
    shortlist_id: uuid.UUID
    name: str


class ShortlistSummaryResponse(BaseModel):
    shortlist_id: uuid.UUID
    name: str
    candidate_count: int
    created_at: datetime


class ShortlistCreateRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def shortlist_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be empty")
        return v.strip()


class CandidateNoteCreateRequest(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def note_body_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body cannot be empty")
        return v.strip()


class CandidateNoteResponse(BaseModel):
    note_id: uuid.UUID
    body: str
    author_user_id: uuid.UUID | None = None
    author_email: str | None = None
    created_at: datetime
    updated_at: datetime


class CandidateActivityResponse(BaseModel):
    activity_id: uuid.UUID
    activity_type: str
    summary: str
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    metadata: dict | None = None
    created_at: datetime


# ── Candidate list (company view) ─────────────────────────────────────────────

class CandidateListItemResponse(BaseModel):
    candidate_id: uuid.UUID
    full_name: str
    email: str
    target_role: str
    overall_score: float | None
    hiring_recommendation: str
    interview_summary: str | None
    report_id: uuid.UUID
    completed_at: datetime | None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    hire_outcome: str | None = None
    skill_tags: list[dict] | None = None
    shortlists: list[ShortlistMembershipResponse] = Field(default_factory=list)
    cheat_risk_score: float | None = None
    red_flag_count: int = 0


# ── Candidate detail (company view) ───────────────────────────────────────────

class ReportWithRoleResponse(BaseModel):
    report_id: uuid.UUID
    interview_id: uuid.UUID | None = None
    target_role: str
    overall_score: float | None
    hard_skills_score: float | None
    soft_skills_score: float | None
    communication_score: float | None
    problem_solving_score: float | None = None
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    hiring_recommendation: str
    interview_summary: str | None
    created_at: datetime
    competency_scores: list[dict] | None = None
    skill_tags: list[dict] | None = None
    red_flags: list[dict] | None = None
    response_consistency: float | None = None


class HireOutcomeRequest(BaseModel):
    outcome: str  # hired | rejected | interviewing | no_show
    notes: str | None = None


class HireOutcomeResponse(BaseModel):
    outcome: str
    notes: str | None
    updated_at: datetime


class CandidateDetailResponse(BaseModel):
    candidate_id: uuid.UUID
    full_name: str
    email: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    hire_outcome: str | None = None
    hire_notes: str | None = None
    shortlists: list[ShortlistMembershipResponse] = Field(default_factory=list)
    reports: list[ReportWithRoleResponse]


class AnalyticsBreakdownItemResponse(BaseModel):
    key: str
    label: str
    count: int


class AnalyticsTemplatePerformanceResponse(BaseModel):
    template_id: uuid.UUID
    template_name: str
    target_role: str
    completed_count: int
    average_score: float | None = None


class AnalyticsRedFlagSummaryResponse(BaseModel):
    candidates_with_flags: int
    total_flags: int


class AnalyticsOverviewResponse(BaseModel):
    total_candidates: int
    total_reports: int
    shortlisted_candidates: int
    role_breakdown: list[AnalyticsBreakdownItemResponse]
    recommendation_breakdown: list[AnalyticsBreakdownItemResponse]
    cheat_risk_breakdown: list[AnalyticsBreakdownItemResponse]
    red_flag_summary: AnalyticsRedFlagSummaryResponse
    template_performance: list[AnalyticsTemplatePerformanceResponse]


class AnalyticsFunnelRowResponse(BaseModel):
    recommendation: str
    total: int
    unreviewed: int
    interviewing: int
    hired: int
    rejected: int
    no_show: int


class AnalyticsFunnelResponse(BaseModel):
    rows: list[AnalyticsFunnelRowResponse]


class AnalyticsSalaryBucketResponse(BaseModel):
    score_range: str
    median_min: float | None
    median_max: float | None
    count: int


class AnalyticsSalaryOutcomeTrendResponse(BaseModel):
    outcome: str
    median_min: float | None
    median_max: float | None
    count: int


class AnalyticsSalaryRoleResponse(BaseModel):
    role: str
    candidate_count: int
    buckets: list[AnalyticsSalaryBucketResponse]
    outcome_trends: list[AnalyticsSalaryOutcomeTrendResponse]


class AnalyticsSalaryResponse(BaseModel):
    role: str | None = None
    shortlist_id: uuid.UUID | None = None
    roles: list[AnalyticsSalaryRoleResponse]
