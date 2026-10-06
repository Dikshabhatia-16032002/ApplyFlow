from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(default_factory=list)
    resume_id: UUID | None = None
    email_template_id: UUID | None = None
    priority: int = Field(default=0, ge=-1000, le=10000)
    is_active: bool = True


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    resume_id: UUID | None = None
    email_template_id: UUID | None = None
    priority: int | None = Field(default=None, ge=-1000, le=10000)
    is_active: bool | None = None


class KeywordReplace(BaseModel):
    keywords: list[str] = Field(default_factory=list)


class ProfileOut(BaseModel):
    id: UUID
    name: str
    resume_id: UUID | None
    email_template_id: UUID | None
    is_active: bool
    priority: int
    keywords: list[str]
    created_at: datetime
    updated_at: datetime
