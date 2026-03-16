import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


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
    reports: list[ReportWithRoleResponse]
