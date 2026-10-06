from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int


class ProfileAssignment(BaseModel):
    profile_ids: list[UUID] = Field(default_factory=list)
