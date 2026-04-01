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
    language: Literal["ru", "en"] = "ru"


class StartInterviewResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    question_count: int
    max_questions: int
    current_question: str
    language: Literal["ru", "en"] = "ru"


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
    is_followup: bool = False  # True when the next question is a follow-up/verification
    question_type: str = "main"  # main | followup | verification | deep_technical | edge_cases


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
    language: Literal["ru", "en"] = "ru"
    started_at: datetime | None
    completed_at: datetime | None
    messages: list[InterviewMessageResponse]
    has_report: bool
    report_id: uuid.UUID | None


class BehavioralSignalsRequest(BaseModel):
    response_times: list[dict] = []  # [{q: int, seconds: float}]
    paste_count: int = 0
    tab_switches: int = 0
    face_away_pct: float | None = None


class ReplayTurn(BaseModel):
    question_number: int
    question: str
    answer: str
    question_time: datetime | None
    answer_time: datetime | None
    analysis: dict | None  # QuestionAnalysis dict from per_question_analysis


class InterviewReplayResponse(BaseModel):
    interview_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    target_role: str
    completed_at: datetime | None
    turns: list[ReplayTurn]


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
