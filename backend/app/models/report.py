import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssessmentReport(Base):
    __tablename__ = "assessment_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), unique=True, nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)

    # Scores (0.0 – 10.0)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hard_skills_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    soft_skills_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    communication_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    problem_solving_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Qualitative arrays
    strengths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Hiring signal
    hiring_recommendation: Mapped[str] = mapped_column(String(50), nullable=False)
    # strong_yes | yes | maybe | no

    # Short summary for candidate marketplace card
    interview_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scientific assessment fields (nullable for backward compat)
    competency_scores: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{competency, category, score, weight, evidence, reasoning}]
    per_question_analysis: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{question_number, targeted_competencies, answer_quality, evidence, skills_mentioned, red_flags, specificity, depth}]
    skill_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{skill, proficiency, mentions_count}]
    red_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{flag, evidence, severity}]
    response_consistency: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    competency_confidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision_policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cheat_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cheat_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # list of strings describing behavioral signals that triggered cheat risk

    # Audit trail
    full_report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    interview: Mapped["Interview"] = relationship("Interview")  # type: ignore
    candidate: Mapped["Candidate"] = relationship("Candidate")  # type: ignore
