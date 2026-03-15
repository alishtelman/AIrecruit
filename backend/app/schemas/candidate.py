import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


class CandidateRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("full_name")
    @classmethod
    def full_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("full_name cannot be empty")
        return v.strip()


class CandidateResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateWithUserResponse(BaseModel):
    """Full profile returned after registration or /me for candidates."""
    user: "UserResponse"
    candidate: CandidateResponse

    model_config = {"from_attributes": True}


# Avoid circular import — inline import at bottom
from app.schemas.user import UserResponse  # noqa: E402

CandidateWithUserResponse.model_rebuild()
