from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ResumeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    is_default: bool | None = None
    profile_ids: list[UUID] | None = None


class ResumeOut(BaseModel):
    id: UUID
    name: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    is_active: bool
    is_default: bool
    profile_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
