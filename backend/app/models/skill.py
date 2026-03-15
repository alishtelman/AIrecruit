import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assessment_reports.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)  # normalized lowercase
    proficiency: Mapped[str] = mapped_column(String(50), nullable=False)  # beginner | intermediate | advanced | expert
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
