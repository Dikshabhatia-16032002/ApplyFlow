"""Google sign-in for Gmail send and the one spreadsheet."""

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import get_settings
from app.models import AppSettings, GmailCredential, User
from app.services.token_crypto import encrypt_secret

GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
SPREADSHEETS = "https://www.googleapis.com/auth/spreadsheets"
REQUESTED_SCOPES = (GMAIL_SEND, SPREADSHEETS, "openid", "email")
_STATE_TTL_SECONDS = 600
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def authorization_url() -> str:
    settings = _require_oauth_config()
    query = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUESTED_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": _issue_state(settings.app_encryption_key),
        }
    )
    return f"{_AUTH_URL}?{query}"


def connect_from_callback(session: Session, code: str, state: str) -> None:
    settings = _require_oauth_config()
    if not _valid_state(settings.app_encryption_key, state):
        raise AppError(400, "invalid_oauth_state", "The Google sign-in expired. Connect again")
    token = exchange_code(code)
    refresh = token.get("refresh_token")
    access = token.get("access_token")
    if not isinstance(refresh, str) or not refresh:
        raise AppError(400, "oauth_missing_refresh_token", "Google did not return a refresh token. Connect again")
    if not isinstance(access, str) or not access:
        raise AppError(400, "oauth_exchange_failed", "Google did not accept the sign-in")
    email = fetch_email(access).strip().lower()
    if not email:
        raise AppError(400, "oauth_missing_email", "Google did not return an email address")

    user = session.scalar(select(User).order_by(User.created_at).limit(1))
    if user is None:
        user = User(display_name="Operator")
        session.add(user)
        session.flush()
    user.email = email

    expires_in = token.get("expires_in")
    expiry = None
    if isinstance(expires_in, int):
        expiry = datetime.now(UTC) + timedelta(seconds=expires_in)
    granted = token.get("scope")
    scopes = granted if isinstance(granted, str) and granted else " ".join(REQUESTED_SCOPES)

    credential = session.scalar(select(GmailCredential).where(GmailCredential.user_id == user.id))
    if credential is None:
        credential = GmailCredential(
            user_id=user.id,
            google_email=email,
            refresh_token_encrypted=encrypt_secret(refresh),
            scopes=scopes,
        )
        session.add(credential)
    credential.google_email = email
    credential.refresh_token_encrypted = encrypt_secret(refresh)
    credential.access_token_encrypted = encrypt_secret(access)
    credential.token_expiry = expiry
    credential.scopes = scopes
    credential.revoked_at = None
    settings_row = session.get(AppSettings, 1)
    if settings_row is not None:
        settings_row.gmail_reconnect_required = False
    session.flush()


def connection_status(session: Session) -> dict[str, object]:
    credential = session.scalar(
        select(GmailCredential)
        .where(GmailCredential.revoked_at.is_(None))
        .order_by(GmailCredential.connected_at.desc())
        .limit(1)
    )
    if credential is None:
        return {"connected": False, "email": None, "scopes": [], "connected_at": None}
    return {
        "connected": True,
        "email": credential.google_email,
        "scopes": [scope for scope in credential.scopes.split() if scope],
        "connected_at": credential.connected_at,
    }


def disconnect(session: Session) -> dict[str, object]:
    credential = session.scalar(select(GmailCredential).where(GmailCredential.revoked_at.is_(None)).limit(1))
    if credential is None:
        return connection_status(session)
    credential.revoked_at = datetime.now(UTC)
    credential.refresh_token_encrypted = encrypt_secret("revoked")
    credential.access_token_encrypted = None
    credential.token_expiry = None
    session.flush()
    return connection_status(session)


def exchange_code(code: str) -> dict[str, object]:
    settings = get_settings()
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    return _post_json(_TOKEN_URL, body)


def fetch_email(access_token: str) -> str:
    request = urllib.request.Request(_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise AppError(400, "oauth_missing_email", "Google did not return an email address") from exc
    email = payload.get("email") if isinstance(payload, dict) else None
    if not isinstance(email, str):
        raise AppError(400, "oauth_missing_email", "Google did not return an email address")
    return email


def frontend_redirect(query: str) -> str:
    origin = get_settings().frontend_origin.rstrip("/")
    return f"{origin}/sheet{query}"


def _require_oauth_config():
    settings = get_settings()
    if not settings.google_client_id.strip() or not settings.google_client_secret.strip():
        raise AppError(503, "oauth_not_configured", "Set the Google client id and secret before connecting")
    if not settings.app_encryption_key.strip():
        raise AppError(503, "oauth_not_configured", "Set APP_ENCRYPTION_KEY before connecting Google")
    return settings


def _issue_state(secret: str) -> str:
    payload = f"{int(time.time())}.{secrets.token_urlsafe(18)}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _valid_state(secret: str, state: str) -> bool:
    issued_text, separator, rest = state.partition(".")
    nonce, separator_2, signature = rest.partition(".")
    if not separator or not separator_2 or not issued_text or not nonce or not signature:
        return False
    payload = f"{issued_text}.{nonce}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    try:
        issued = int(issued_text)
    except ValueError:
        return False
    age = int(time.time()) - issued
    return 0 <= age <= _STATE_TTL_SECONDS


def _post_json(url: str, body: bytes) -> dict[str, object]:
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise AppError(400, "oauth_exchange_failed", "Google did not accept the sign-in") from exc
    if not isinstance(payload, dict):
        raise AppError(400, "oauth_exchange_failed", "Google did not accept the sign-in")
    return payload
