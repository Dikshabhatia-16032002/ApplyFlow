"""Encrypt OAuth tokens at rest. Plain tokens are never logged."""

from cryptography.fernet import Fernet, InvalidToken

from app.api.errors import AppError
from app.config import get_settings


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise AppError(500, "token_unreadable", "The stored Google token could not be read") from exc


def _fernet() -> Fernet:
    key = get_settings().app_encryption_key.strip()
    if not key:
        raise AppError(503, "oauth_not_configured", "Set APP_ENCRYPTION_KEY before connecting Google")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise AppError(503, "oauth_not_configured", "APP_ENCRYPTION_KEY must be a Fernet key") from exc
