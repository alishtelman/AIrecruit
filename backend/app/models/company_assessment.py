import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _token() -> str:
    return secrets.token_urlsafe(24)


class CompanyAssessment(Base):
    """
    Company-initiated private assessment campaign.

    Flow:
      1. Company admin creates an assessment → invite_token generated
      2. Invitee opens /employee/invite/{token} → registers/logs in as candidate
      3. Interview is started and linked via interview_id
      4. Report is visible to the company (private)

    status:
      pending    — invite sent, not yet started
      opened     — invite landing page opened, not yet started
      in_progress — interview started
      completed  — report generated
      expired    — invite can no longer be started
    """
    __tablename__ = "company_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    employee_email: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    assessment_type: Mapped[str] = mapped_column(String(50), nullable=False, default="employee_internal")
    target_role: Mapped[str] = mapped_column(String(100), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
    )
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=_token)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending | opened | in_progress | completed | expired
    module_plan: Mapped[list | None] = mapped_column(JSON, nullable=True)
    current_module_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    branding_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branding_logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    company: Mapped["Company"] = relationship("Company", foreign_keys=[company_id])  # type: ignore
    interview: Mapped["Interview"] = relationship("Interview", foreign_keys=[interview_id])  # type: ignore
    template: Mapped["InterviewTemplate | None"] = relationship("InterviewTemplate", foreign_keys=[template_id])  # type: ignore
