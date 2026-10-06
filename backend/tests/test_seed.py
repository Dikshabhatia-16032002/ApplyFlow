import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Profile
from app.seed import PROFILE_SEEDS, counts, keywords_for, seed


def _postgres_available() -> bool:
    try:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _postgres_available(), reason="Postgres is not running")


@pytest.fixture(scope="module")
def migrated_database() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")


def test_seed_is_idempotent(migrated_database: None) -> None:
    engine = create_engine(get_settings().database_url)
    expected_keywords = sum(len(keywords_for(name, raw)) for name, raw in PROFILE_SEEDS)
    expected_names = {name for name, _raw in PROFILE_SEEDS}

    with Session(engine) as session:
        seed(session)
        session.commit()
        after_first = counts(session)
        names = set(session.scalars(select(Profile.name)).all())

    with Session(engine) as session:
        second = seed(session)
        session.commit()
        after_second = counts(session)

    assert expected_names <= names
    assert after_first["users"] >= 1
    assert after_first["profiles"] >= 7
    assert after_first["keywords"] >= expected_keywords
    assert after_first["settings"] == 1
    assert second.user_created is False
    assert second.profiles_created == 0
    assert second.keywords_created == 0
    assert second.settings_created is False
    assert after_second == after_first
