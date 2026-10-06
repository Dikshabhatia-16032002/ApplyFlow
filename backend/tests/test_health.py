import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.main import app


def _postgres_available() -> bool:
    try:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _postgres_available(), reason="Postgres is not running")


def test_health_reports_database() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert body["dry_run"] is True
    assert isinstance(body["gmail_connected"], bool)
    assert isinstance(body["sheet_connected"], bool)
    assert isinstance(body["gmail_reconnect_required"], bool)
    assert "redis" in body
