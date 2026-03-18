import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

PROFILE_VISIBILITY_PRIVATE = "private"
PROFILE_VISIBILITY_MARKETPLACE = "marketplace"
PROFILE_VISIBILITY_DIRECT_LINK = "direct_link"
PROFILE_VISIBILITY_REQUEST_ONLY = "request_only"
PROFILE_VISIBILITIES = {
    PROFILE_VISIBILITY_PRIVATE,
    PROFILE_VISIBILITY_MARKETPLACE,
    PROFILE_VISIBILITY_DIRECT_LINK,
    PROFILE_VISIBILITY_REQUEST_ONLY,
}


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), server_default="USD", nullable=False)
    profile_visibility: Mapped[str] = mapped_column(String(32), server_default=PROFILE_VISIBILITY_MARKETPLACE, nullable=False)
    public_share_token: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship("User")  # type: ignore
    resumes: Mapped[list["Resume"]] = relationship("Resume", back_populates="candidate", order_by="Resume.created_at")  # type: ignore
