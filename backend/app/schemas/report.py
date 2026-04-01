import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class CompetencyScore(BaseModel):
    competency: str
    category: str
    score: float
    weight: float
    evidence: str
    reasoning: str = ""


class QuestionAnalysis(BaseModel):
    question_number: int
    targeted_competencies: list[str] = []
    answer_quality: float
    evidence: str = ""
    skills_mentioned: list[dict] = []
    red_flags: list[str] = []
    specificity: str = "medium"
    depth: str = "adequate"
    ai_likelihood: float | None = None


class SkillTag(BaseModel):
    skill: str
    proficiency: str
    mentions_count: int = 1


class RedFlag(BaseModel):
    flag: str
    evidence: str
    severity: str = "low"


class ReportSummaryBlock(BaseModel):
    score: float | None
    hiring_recommendation: str
    top_strengths: list[str]
    top_weaknesses: list[str]


class InterviewSummaryModel(BaseModel):
    class TopicOutcome(BaseModel):
        slot: int
        label: str
        signal: str
        outcome: str
        verification_target: str | None = None

    role: str
    core_topics: int
    total_turns: int
    extra_turns: int
    covered_competencies: int
    coverage_label: str
    signal_quality: str
    validated_topics: int = 0
    partial_topics: int = 0
    unverified_claim_topics: int = 0
    honest_gaps: int
    generic_or_evasive_topics: int
    strong_topics: int
    topic_outcomes: list[TopicOutcome] = []


class AssessmentReportResponse(BaseModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    candidate_id: uuid.UUID
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
    model_version: str
    created_at: datetime

    # Scientific assessment fields
    competency_scores: list[CompetencyScore] | None = None
    per_question_analysis: list[QuestionAnalysis] | None = None
    skill_tags: list[SkillTag] | None = None
    red_flags: list[RedFlag] | None = None
    response_consistency: float | None = None
    overall_confidence: float | None = None
    competency_confidence: dict[str, float] | None = None
    confidence_reasons: list[str] | None = None
    evidence_coverage: dict | None = None
    decision_policy_version: str | None = None
    cheat_risk_score: float | None = None
    cheat_flags: list[str] | None = None
    summary: ReportSummaryBlock | None = None
    summary_model: InterviewSummaryModel | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _pull_summary_model(cls, data):
        full_report_json = None
        if isinstance(data, dict):
            full_report_json = data.get("full_report_json")
        else:
            full_report_json = getattr(data, "full_report_json", None)

        if isinstance(full_report_json, dict):
            summary_model = full_report_json.get("summary_model")
            if isinstance(data, dict):
                data["summary_model"] = summary_model
            else:
                setattr(data, "summary_model", summary_model)
        return data

    @model_validator(mode="after")
    def _build_summary(self) -> "AssessmentReportResponse":
        self.summary = ReportSummaryBlock(
            score=self.overall_score,
            hiring_recommendation=self.hiring_recommendation,
            top_strengths=self.strengths[:2],
            top_weaknesses=self.weaknesses[:2],
        )
        return self
