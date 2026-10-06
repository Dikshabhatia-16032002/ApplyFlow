import logging

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import AppSettings, GmailCredential, SheetConnection

logger = logging.getLogger(__name__)
router = APIRouter()


class HealthBody(BaseModel):
    database: str
    redis: str
    dry_run: bool
    gmail_connected: bool
    sheet_connected: bool
    gmail_reconnect_required: bool


def redis_status(url: str) -> str:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=0.3, socket_timeout=0.3)
        client.ping()
    except redis.RedisError:
        return "unavailable"
    return "ok"


def read_flags(session: Session) -> tuple[bool, bool, bool]:
    gmail_connected = (
        session.scalar(select(GmailCredential.id).where(GmailCredential.revoked_at.is_(None)).limit(1)) is not None
    )
    sheet_connected = session.scalar(select(SheetConnection.id).limit(1)) is not None
    settings_row = session.get(AppSettings, 1)
    reconnect = bool(settings_row.gmail_reconnect_required) if settings_row is not None else False
    return gmail_connected, sheet_connected, reconnect


@router.get("/health")
def health() -> JSONResponse:
    settings = get_settings()
    database = "ok"
    gmail_connected = False
    sheet_connected = False
    reconnect = False
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            gmail_connected, sheet_connected, reconnect = read_flags(session)
    except Exception:
        database = "unavailable"
        logger.exception("database health check failed")

    body = HealthBody(
        database=database,
        redis=redis_status(settings.redis_url),
        dry_run=settings.dry_run,
        gmail_connected=gmail_connected,
        sheet_connected=sheet_connected,
        gmail_reconnect_required=reconnect,
    )
    status_code = 200 if database == "ok" else 503
    return JSONResponse(status_code=status_code, content=body.model_dump())
