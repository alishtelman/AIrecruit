import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _token() -> str:
    return secrets.token_urlsafe(24)


class CompanyAssessment(Base):
    """
    Company-initiated assessment invite for an employee.

    Flow:
      1. Company admin creates an assessment → invite_token generated
      2. Employee opens /employee/invite/{token} → registers/logs in as candidate
      3. Interview is started and linked via interview_id
      4. Report is visible to the company (private)

    status:
      pending    — invite sent, not yet started
      in_progress — interview started
      completed  — report generated
      expired    — invite link expired (optional)
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
    target_role: Mapped[str] = mapped_column(String(100), nullable=False)
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=_token)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending | in_progress | completed
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    company: Mapped["Company"] = relationship("Company", foreign_keys=[company_id])  # type: ignore
    interview: Mapped["Interview"] = relationship("Interview", foreign_keys=[interview_id])  # type: ignore
