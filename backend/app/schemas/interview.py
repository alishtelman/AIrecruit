import uuid
from datetime import datetime
from typing import Any, Literal

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


class InterviewModuleSessionResponse(BaseModel):
    module_type: str
    module_title: str | None = None
    scenario_id: str | None = None
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    stack_focus: str | None = None
    preferred_language: str | None = None
    workspace_hint: str | None = None
    stage_key: str | None = None
    stage_title: str | None = None
    stage_index: int = 0
    stage_count: int = 0


class CodingTaskArtifactRequest(BaseModel):
    language: str | None = "python"
    code: str

    @field_validator("code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code cannot be empty")
        return v


class CodingTaskArtifactResponse(BaseModel):
    interview_id: uuid.UUID
    language: str | None = "python"
    code: str = ""
    updated_at: datetime | None = None


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
    module_session: InterviewModuleSessionResponse | None = None


class ReportSummary(BaseModel):
    overall_score: float | None
    hiring_recommendation: str
    interview_summary: str | None


class AssessmentProgressResponse(BaseModel):
    assessment_id: uuid.UUID
    invite_token: str
    assessment_status: str
    has_remaining_modules: bool
    module_count: int
    current_module_index: int
    current_module_type: str | None = None
    current_module_title: str | None = None


class FinishInterviewResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    report_id: uuid.UUID | None = None
    summary: ReportSummary | None = None
    assessment_progress: AssessmentProgressResponse | None = None
    module_session: InterviewModuleSessionResponse | None = None


class ReportProcessingDiagnostics(BaseModel):
    attempt_count: int = 0
    max_attempts: int = 0
    last_phase: str | None = None
    last_status: Literal["pending", "processing", "ready", "failed"] | None = None
    last_started_at: str | None = None
    last_completed_at: str | None = None
    last_transition_at: str | None = None
    next_retry_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None


class InterviewReportStatusResponse(BaseModel):
    interview_id: uuid.UUID
    status: str
    processing_state: Literal["pending", "processing", "ready", "failed"]
    report_id: uuid.UUID | None = None
    summary: ReportSummary | None = None
    failure_reason: str | None = None
    diagnostics: ReportProcessingDiagnostics | None = None
    assessment_progress: AssessmentProgressResponse | None = None
    module_session: InterviewModuleSessionResponse | None = None


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
    assessment_progress: AssessmentProgressResponse | None = None
    module_session: InterviewModuleSessionResponse | None = None


class BehavioralSignalsRequest(BaseModel):
    response_times: list[dict] = []  # [{q: int, seconds: float}]
    paste_count: int = 0
    tab_switches: int = 0
    face_away_pct: float | None = None
    speech_activity_pct: float | None = None
    silence_pct: float | None = None
    long_silence_count: int = 0
    speech_segment_count: int = 0
    events: list[dict[str, Any]] = []
    policy_mode: Literal["observe_only", "strict_flagging"] | None = None


class ReplayTurn(BaseModel):
    question_number: int
    question: str
    answer: str
    question_time: datetime | None
    answer_time: datetime | None
    analysis: dict | None  # QuestionAnalysis dict from per_question_analysis
    stage_key: str | None = None
    stage_title: str | None = None


class TranscriptBlockResponse(BaseModel):
    speaker: Literal["interviewer", "candidate"]
    kind: Literal["question", "answer"]
    turn_number: int
    text: str
    timestamp: datetime | None


class InterviewReplayResponse(BaseModel):
    interview_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    target_role: str
    completed_at: datetime | None
    turns: list[ReplayTurn]
    transcript_blocks: list[TranscriptBlockResponse] | None = None
    transcript_text: str | None = None
    module_session: InterviewModuleSessionResponse | None = None


class ProctoringTimelineEventResponse(BaseModel):
    event_type: str
    severity: Literal["info", "medium", "high"] = "info"
    occurred_at: str | None = None
    source: str = "client"
    details: dict[str, Any] = {}


class ProctoringTimelineResponse(BaseModel):
    interview_id: uuid.UUID
    report_id: uuid.UUID | None = None
    policy_mode: Literal["observe_only", "strict_flagging"] = "observe_only"
    risk_level: Literal["low", "medium", "high"] = "low"
    total_events: int = 0
    high_severity_count: int = 0
    speech_activity_pct: float | None = None
    silence_pct: float | None = None
    long_silence_count: int = 0
    speech_segment_count: int = 0
    events: list[ProctoringTimelineEventResponse] = []


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
