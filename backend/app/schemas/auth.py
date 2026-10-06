from datetime import datetime

from pydantic import BaseModel


class AuthorizationOut(BaseModel):
    authorization_url: str


class GoogleStatusOut(BaseModel):
    connected: bool
    email: str | None
    scopes: list[str]
    connected_at: datetime | None
