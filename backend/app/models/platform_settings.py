from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlatformSettings(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    candidate_registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    company_registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    employee_invites_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    maintenance_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    proctoring_policy_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interviewer_model_preference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assessor_model_preference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    interviewer_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    assessor_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    interviewer_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessor_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
