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


class CompanyAISettingsUpdateRequest(BaseModel):
    proctoring_policy_mode: str | None = None
    interviewer_model_preference: str | None = None
    assessor_model_preference: str | None = None

    @field_validator("proctoring_policy_mode")
    @classmethod
    def normalize_proctoring_policy_mode(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        if normalized not in {"observe_only", "strict_flagging"}:
            raise ValueError("Unsupported proctoring_policy_mode")
        return normalized

    @field_validator("interviewer_model_preference", "assessor_model_preference")
    @classmethod
    def normalize_model_preference(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip()
        if not normalized:
            return None
        if len(normalized) > 120:
            raise ValueError("Model preference must be 120 characters or fewer")
        return normalized


class CompanyAISettingsResponse(BaseModel):
    proctoring_policy_mode: str
    interviewer_provider: str
    interviewer_runtime_model: str
    interviewer_model_preference: str | None = None
    assessor_provider: str
    assessor_runtime_model: str
    assessor_model_preference: str | None = None
    tts_provider: str
    tts_fallback_provider: str
    mock_ai_available: bool = False
    runtime_applied_fields: list[str] = Field(default_factory=list)
    stored_preference_fields: list[str] = Field(default_factory=list)


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


class AnalyticsSalaryBandResponse(BaseModel):
    candidate_count: int
    range_min: float | None = None
    median_min: float | None = None
    median_max: float | None = None
    range_max: float | None = None


class AnalyticsSalaryRoleResponse(BaseModel):
    role: str
    currency: str
    candidate_count: int
    market_band: AnalyticsSalaryBandResponse
    shortlisted_band: AnalyticsSalaryBandResponse | None = None
    buckets: list[AnalyticsSalaryBucketResponse]
    outcome_trends: list[AnalyticsSalaryOutcomeTrendResponse]


class AnalyticsSalaryResponse(BaseModel):
    role: str | None = None
    shortlist_id: uuid.UUID | None = None
    roles: list[AnalyticsSalaryRoleResponse]
