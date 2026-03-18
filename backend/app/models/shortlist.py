import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CompanyShortlist(Base):
    __tablename__ = "company_shortlists"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_company_shortlist_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    company: Mapped["Company"] = relationship("Company", foreign_keys=[company_id])  # type: ignore
    memberships: Mapped[list["CompanyShortlistCandidate"]] = relationship(
        "CompanyShortlistCandidate",
        back_populates="shortlist",
        cascade="all, delete-orphan",
    )


class CompanyShortlistCandidate(Base):
    __tablename__ = "company_shortlist_candidates"
    __table_args__ = (UniqueConstraint("shortlist_id", "candidate_id", name="uq_shortlist_candidate"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shortlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_shortlists.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    shortlist: Mapped["CompanyShortlist"] = relationship("CompanyShortlist", back_populates="memberships")  # type: ignore
