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


class PlatformSettingsResponse(BaseModel):
    candidate_registration_enabled: bool
    company_registration_enabled: bool
    employee_invites_enabled: bool
    maintenance_mode_enabled: bool
    proctoring_policy_mode: str
    interviewer_model_preference: str | None = None
    assessor_model_preference: str | None = None
    created_at: datetime
    updated_at: datetime


class PlatformSettingsUpdateRequest(BaseModel):
    candidate_registration_enabled: bool | None = None
    company_registration_enabled: bool | None = None
    employee_invites_enabled: bool | None = None
    maintenance_mode_enabled: bool | None = None


class PlatformAISettingsUpdateRequest(BaseModel):
    proctoring_policy_mode: str | None = None
    interviewer_model_preference: str | None = None
    assessor_model_preference: str | None = None


class AdminActivationUpdateRequest(BaseModel):
    is_active: bool


class AdminInterviewListItemResponse(BaseModel):
    id: uuid.UUID
    candidate_name: str
    candidate_email: EmailStr
    target_role: str
    status: str
    language: str
    created_at: datetime
    completed_at: datetime | None = None
    report_id: uuid.UUID | None = None
    overall_score: float | None = None
    hiring_recommendation: str | None = None
    processing_state: str


class AdminInterviewListResponse(BaseModel):
    items: list[AdminInterviewListItemResponse]


class AdminUserListItemResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItemResponse]


class AdminCompanyListItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    owner_email: str | None = None
    is_active: bool
    member_count: int = 0
    created_at: datetime


class AdminCompanyListResponse(BaseModel):
    items: list[AdminCompanyListItemResponse]


class AdminReportListItemResponse(BaseModel):
    id: uuid.UUID
    candidate_name: str
    candidate_email: EmailStr
    target_role: str
    overall_score: float | None = None
    hiring_recommendation: str
    created_at: datetime


class AdminReportListResponse(BaseModel):
    items: list[AdminReportListItemResponse]


class AdminAuditLogItemResponse(BaseModel):
    id: uuid.UUID
    actor_email: EmailStr
    action: str
    entity_type: str
    entity_id: str | None = None
    summary: str
    metadata_json: dict | None = None
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogItemResponse]
