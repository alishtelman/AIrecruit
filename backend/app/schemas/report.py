import uuid
from datetime import datetime

from pydantic import BaseModel


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


class SkillTag(BaseModel):
    skill: str
    proficiency: str
    mentions_count: int = 1


class RedFlag(BaseModel):
    flag: str
    evidence: str
    severity: str = "low"


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

    model_config = {"from_attributes": True}
