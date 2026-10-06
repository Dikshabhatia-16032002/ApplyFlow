import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.db import SessionLocal
from app.main import app

pytest_plugins = ["tests.mail_factory"]


def postgres_available() -> bool:
    try:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


@pytest.fixture
def client():
    if not postgres_available():
        pytest.skip("Postgres is not running")
    command.upgrade(Config("alembic.ini"), "head")
    with TestClient(app) as test_client:
        yield test_client
    with SessionLocal() as session:
        session.execute(
            text(
                """
                UPDATE profiles SET resume_id = NULL
                WHERE resume_id IN (SELECT id FROM resumes WHERE name LIKE 'Test %')
                """
            )
        )
        session.execute(
            text(
                """
                UPDATE profiles SET email_template_id = NULL
                WHERE email_template_id IN (
                    SELECT id FROM email_templates
                    WHERE name LIKE 'Test %' OR name LIKE 'Copy of Test%'
                )
                """
            )
        )
        session.execute(text("DELETE FROM profiles WHERE name LIKE 'Test %'"))
        session.execute(text("DELETE FROM resumes WHERE name LIKE 'Test %'"))
        session.execute(
            text("DELETE FROM email_templates WHERE name LIKE 'Test %' OR name LIKE 'Copy of Test%'")
        )
        session.commit()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    return tmp_path
