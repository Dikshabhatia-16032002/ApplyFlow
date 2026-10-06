from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    is_active: bool = True
    is_default: bool = False
    profile_ids: list[UUID] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)
    is_active: bool | None = None
    is_default: bool | None = None
    profile_ids: list[UUID] | None = None


class TemplatePreviewRequest(BaseModel):
    template_id: UUID | None = None
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)
    name: str | None = None
    company: str | None = None
    role: str | None = None
    location: str | None = None
    mobile: str | None = None
    linkedin_url: str | None = None


class TemplateOut(BaseModel):
    id: UUID
    name: str
    subject: str
    body: str
    is_active: bool
    is_default: bool
    profile_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class TemplatePreviewOut(BaseModel):
    subject: str
    body: str
    empty_variables: list[str]
    unknown_tokens: list[str]
