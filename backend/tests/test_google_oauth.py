from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import GmailCredential, User
from app.services import google_oauth
from app.services.token_crypto import decrypt_secret


def test_start_returns_the_gmail_and_sheets_consent_url(client, monkeypatch) -> None:
    _configure(monkeypatch)
    response = client.get("/api/v1/auth/google/start")
    assert response.status_code == 200
    parsed = urlparse(response.json()["authorization_url"])
    params = parse_qs(parsed.query)
    scopes = set(params["scope"][0].split())
    assert parsed.netloc == "accounts.google.com"
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/spreadsheets" in scopes
    assert params["redirect_uri"] == ["http://localhost:8000/api/v1/auth/google/callback"]
    assert params["access_type"] == ["offline"]


def test_callback_stores_an_encrypted_token_and_disconnects(client, monkeypatch) -> None:
    _configure(monkeypatch)

    def exchange(code: str) -> dict[str, object]:
        assert code == "auth-code"
        return {"refresh_token": "refresh-secret", "access_token": "access-secret", "expires_in": 3600, "scope": "email"}

    monkeypatch.setattr(google_oauth, "exchange_code", exchange)
    monkeypatch.setattr(google_oauth, "fetch_email", lambda _token: "Operator@Gmail.test")
    start = client.get("/api/v1/auth/google/start")
    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]

    try:
        callback = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 307
        assert callback.headers["location"] == "http://localhost:5173/sheet?google=connected"

        status = client.get("/api/v1/auth/google/status")
        assert status.status_code == 200
        body = status.json()
        assert body["connected"] is True
        assert body["email"] == "operator@gmail.test"
        assert "refresh-secret" not in status.text
        assert "access-secret" not in status.text

        with SessionLocal() as session:
            credential = session.scalar(
                select(GmailCredential).where(GmailCredential.google_email == "operator@gmail.test")
            )
            assert credential is not None
            assert decrypt_secret(credential.refresh_token_encrypted) == "refresh-secret"
            assert credential.refresh_token_encrypted != "refresh-secret"

        disconnected = client.post("/api/v1/auth/google/disconnect")
        assert disconnected.status_code == 200
        assert disconnected.json()["connected"] is False
        assert "refresh-secret" not in disconnected.text
    finally:
        with SessionLocal() as session:
            session.execute(delete(GmailCredential).where(GmailCredential.google_email == "operator@gmail.test"))
            user = session.scalar(select(User).limit(1))
            if user is not None and user.email == "operator@gmail.test":
                user.email = None
            session.commit()


def test_callback_rejects_a_bad_state(client, monkeypatch) -> None:
    _configure(monkeypatch)
    response = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": "not-a-real-state"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/sheet?google_error=invalid_oauth_state"


def _configure(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8000/api/v1/auth/google/callback")
    monkeypatch.setattr(settings, "frontend_origin", "http://localhost:5173")
    monkeypatch.setattr(settings, "app_encryption_key", Fernet.generate_key().decode())
