import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

# Allowed roles — single source of truth shared with interviewer.py question banks
TargetRole = Literal[
    "backend_engineer",
    "frontend_engineer",
    "qa_engineer",
    "devops_engineer",
    "data_scientist",
    "product_manager",
    "mobile_engineer",
    "designer",
]


class StartInterviewRequest(BaseModel):
    target_role: TargetRole
    template_id: uuid.UUID | None = None


class StartInterviewResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    question_count: int
    max_questions: int
    current_question: str


class SendMessageRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be empty")
        return v.strip()


class SendMessageResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    question_count: int
    max_questions: int
    current_question: str | None  # null when max_questions reached — call /finish


class ReportSummary(BaseModel):
    overall_score: float | None
    hiring_recommendation: str
    interview_summary: str | None


class FinishInterviewResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    report_id: uuid.UUID
    summary: ReportSummary


class InterviewMessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InterviewDetailResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    target_role: str
    question_count: int
    max_questions: int
    started_at: datetime | None
    completed_at: datetime | None
    messages: list[InterviewMessageResponse]
    has_report: bool
    report_id: uuid.UUID | None


class InterviewListItemResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    target_role: str
    question_count: int
    max_questions: int
    started_at: datetime | None
    completed_at: datetime | None
    has_report: bool
    report_id: uuid.UUID | None
