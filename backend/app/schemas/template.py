import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    target_role: str
    questions: list[str] = Field(..., min_length=1)
    description: str | None = None
    is_public: bool = False


class TemplateResponse(BaseModel):
    template_id: uuid.UUID
    company_id: uuid.UUID
    name: str
    target_role: str
    questions: list[str]
    description: str | None
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}
