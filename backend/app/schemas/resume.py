import uuid

from pydantic import BaseModel


class ResumeUploadResponse(BaseModel):
    resume_id: uuid.UUID
    file_name: str
    text_length: int
    is_active: bool
