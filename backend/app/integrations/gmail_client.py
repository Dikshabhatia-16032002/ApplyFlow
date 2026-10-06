"""Gmail send. Tests replace `GmailClient` with `FakeGmailClient`."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import get_settings
from app.models import GmailCredential
from app.services.token_crypto import decrypt_secret, encrypt_secret

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_REFRESH_WINDOW = timedelta(minutes=2)


class GmailError(Exception):
    def __init__(self, code: str, detail: str, *, retryable: bool) -> None:
        self.code = code
        self.detail = detail
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class OutboundMessage:
    to: str
    subject: str
    body: str
    attachment_filename: str
    attachment_bytes: bytes


class GmailClient(Protocol):
    def send(self, message: OutboundMessage) -> str: ...


class FakeGmailClient:
    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []
        self.error: GmailError | None = None

    def send(self, message: OutboundMessage) -> str:
        if self.error is not None:
            raise self.error
        self.sent.append(message)
        return f"test-message-{len(self.sent)}"


class GoogleGmailClient:
    """Refresh the stored token and call users.messages.send. Tokens are never logged."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def send(self, message: OutboundMessage) -> str:
        credential = _active_credential(self._session)
        if credential is None:
            raise GmailError("auth", "Gmail is not connected", retryable=False)
        token = _usable_access_token(self._session, credential)
        raw = _raw_message(message, credential.google_email)
        try:
            return _post_send(token, raw)
        except GmailError as exc:
            if exc.code != "auth":
                raise
        token = _refresh(self._session, credential)
        return _post_send(token, raw)


def get_gmail_client(session: Session) -> GmailClient:
    return GoogleGmailClient(session)


def bearer_token(session: Session) -> str:
    """Return a usable access token for the connected Google account."""
    credential = _active_credential(session)
    if credential is None:
        raise GmailError("auth", "Gmail is not connected", retryable=False)
    return _usable_access_token(session, credential)


def refreshed_bearer_token(session: Session) -> str:
    credential = _active_credential(session)
    if credential is None:
        raise GmailError("auth", "Gmail is not connected", retryable=False)
    return _refresh(session, credential)


def _active_credential(session: Session) -> GmailCredential | None:
    return session.scalar(
        select(GmailCredential)
        .where(GmailCredential.revoked_at.is_(None))
        .order_by(GmailCredential.connected_at.desc())
        .limit(1)
    )


def _usable_access_token(session: Session, credential: GmailCredential) -> str:
    expiry = credential.token_expiry
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    fresh = expiry is not None and expiry > datetime.now(UTC) + _REFRESH_WINDOW
    if fresh and credential.access_token_encrypted:
        try:
            return decrypt_secret(credential.access_token_encrypted)
        except AppError as exc:
            raise GmailError("auth", "Gmail authorization failed", retryable=False) from exc
    return _refresh(session, credential)


def _refresh(session: Session, credential: GmailCredential) -> str:
    settings = get_settings()
    if not settings.google_client_id.strip() or not settings.google_client_secret.strip():
        raise GmailError("auth", "Gmail authorization failed", retryable=False)
    try:
        refresh_token = decrypt_secret(credential.refresh_token_encrypted)
    except AppError as exc:
        raise GmailError("auth", "Gmail authorization failed", retryable=False) from exc
    body = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode()
    payload = _post_form(body)
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise GmailError("auth", "Gmail authorization failed", retryable=False)
    expires_in = payload.get("expires_in")
    credential.access_token_encrypted = encrypt_secret(access)
    if isinstance(expires_in, int):
        credential.token_expiry = datetime.now(UTC) + timedelta(seconds=expires_in)
    session.flush()
    return access


def _post_form(body: bytes) -> dict[str, object]:
    request = urllib.request.Request(_TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise _from_http(exc) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GmailError("auth", "Gmail authorization failed", retryable=False) from exc
    if not isinstance(payload, dict):
        raise GmailError("auth", "Gmail authorization failed", retryable=False)
    return payload


def _post_send(access_token: str, raw: str) -> str:
    body = json.dumps({"raw": raw}).encode()
    request = urllib.request.Request(
        _SEND_URL,
        data=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise _from_http(exc) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GmailError("connection", "Gmail did not respond", retryable=True) from exc
    message_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(message_id, str) or not message_id:
        raise GmailError("gmail_response", "Gmail did not return a message id", retryable=True)
    return message_id


def _from_http(exc: urllib.error.HTTPError) -> GmailError:
    detail = _error_detail(exc)
    if exc.code == 401:
        return GmailError("auth", "Gmail authorization failed", retryable=False)
    if exc.code == 429:
        return GmailError("rate_limit", detail, retryable=True)
    if exc.code in {500, 503}:
        return GmailError("gmail_unavailable", detail, retryable=True)
    lowered = detail.lower()
    if exc.code == 400 and ("recipient" in lowered or "invalid to" in lowered):
        return GmailError("invalid_recipient", detail, retryable=False)
    return GmailError("gmail_rejected", detail, retryable=False)


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode())
    except (json.JSONDecodeError, UnicodeError):
        return "Gmail rejected the message"
    if not isinstance(payload, dict):
        return "Gmail rejected the message"
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    return "Gmail rejected the message"


def _raw_message(message: OutboundMessage, from_email: str) -> str:
    mime = MIMEMultipart()
    mime["To"] = message.to
    mime["From"] = from_email
    mime["Subject"] = message.subject
    mime.attach(MIMEText(message.body, "plain"))
    attachment = MIMEApplication(message.attachment_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=message.attachment_filename)
    mime.attach(attachment)
    encoded = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    return encoded.rstrip("=")
