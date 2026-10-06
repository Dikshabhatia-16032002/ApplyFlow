from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class CampaignOut(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime


class CampaignContactOut(BaseModel):
    id: UUID
    email: str
    name: str | None
    company: str | None
    role: str | None
    original_role: str | None
    status: str
    skip_reason: str | None
    profile_id: UUID | None
    profile_name: str | None
    match_confidence: Decimal | None
    match_method: str | None
    matched_keywords: list[str]
    resume_id: UUID | None
    resume_name: str | None
    template_id: UUID | None
    template_name: str | None
    resume_overridden: bool
    template_overridden: bool


class ContactMatchUpdate(BaseModel):
    profile_id: UUID | None = None
    resume_id: UUID | None = None
    template_id: UUID | None = None
