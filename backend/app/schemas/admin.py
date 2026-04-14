import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class AdminOverviewMetricsResponse(BaseModel):
    total_users: int
    active_candidates: int
    active_companies: int
    company_members: int
    interviews_total: int
    interviews_completed: int
    reports_generated: int


class AdminRuntimeStatusResponse(BaseModel):
    app_env: str
    mock_ai_enabled: bool
    rate_limit_enabled: bool
    platform_admin_bootstrap_enabled: bool


class AdminRecentUserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


class AdminRecentCompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    owner_email: str | None = None
    is_active: bool
    created_at: datetime


class AdminRecentInterviewResponse(BaseModel):
    id: uuid.UUID
    candidate_name: str
    target_role: str
    status: str
    language: str
    created_at: datetime
    completed_at: datetime | None = None
    report_ready: bool = False


class AdminRecentReportResponse(BaseModel):
    id: uuid.UUID
    candidate_name: str
    target_role: str
    overall_score: float | None = None
    hiring_recommendation: str
    created_at: datetime


class AdminOverviewResponse(BaseModel):
    metrics: AdminOverviewMetricsResponse
    runtime: AdminRuntimeStatusResponse
    recent_users: list[AdminRecentUserResponse]
    recent_companies: list[AdminRecentCompanyResponse]
    recent_interviews: list[AdminRecentInterviewResponse]
    recent_reports: list[AdminRecentReportResponse]
