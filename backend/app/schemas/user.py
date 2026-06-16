import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    company_member_role: str | None = None
    company_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    account_type: str

    @field_validator("account_type")
    @classmethod
    def normalize_account_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"candidate", "company", "admin"}:
            return normalized
        if normalized in {"company_admin", "company_member"}:
            return "company"
        if normalized == "platform_admin":
            return "admin"
        raise ValueError("Unsupported login type")
