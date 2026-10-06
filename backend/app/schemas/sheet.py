from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SheetPut(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    sheet_name: str | None = Field(default=None, max_length=200)


class SheetOut(BaseModel):
    spreadsheet_id: str
    spreadsheet_url: str
    sheet_name: str | None
    header_map: dict[str, str] | None
    last_synced_at: datetime | None


class SyncSummary(BaseModel):
    campaign_id: UUID
    rows_read: int
    valid: int
    needs_review: int
    not_sent: int
    already_sent: int
    skipped_invalid: int
    skipped_duplicate: int


class HeaderMapInput(BaseModel):
    email: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=500)
    name: str | None = None
    mobile: str | None = None
    company: str | None = None
    job_description: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    notes: str | None = None

    def as_map(self) -> dict[str, str]:
        values = {
            "email": self.email.strip(),
            "role": self.role.strip(),
            "name": self.name,
            "mobile": self.mobile,
            "company": self.company,
            "job_description": self.job_description,
            "location": self.location,
            "linkedin_url": self.linkedin_url,
            "notes": self.notes,
        }
        return {field: value.strip() for field, value in values.items() if value and value.strip()}
