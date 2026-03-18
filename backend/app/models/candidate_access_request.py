import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

ACCESS_REQUEST_PENDING = "pending"
ACCESS_REQUEST_APPROVED = "approved"
ACCESS_REQUEST_DENIED = "denied"
ACCESS_REQUEST_STATUSES = {
    ACCESS_REQUEST_PENDING,
    ACCESS_REQUEST_APPROVED,
    ACCESS_REQUEST_DENIED,
}


class CandidateAccessRequest(Base):
    __tablename__ = "candidate_access_requests"
    __table_args__ = (
        UniqueConstraint("candidate_id", "company_id", name="uq_candidate_access_request_candidate_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ACCESS_REQUEST_PENDING, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    candidate: Mapped["Candidate"] = relationship("Candidate")  # type: ignore
    company: Mapped["Company"] = relationship("Company")  # type: ignore
    requested_by: Mapped["User | None"] = relationship("User")  # type: ignore
