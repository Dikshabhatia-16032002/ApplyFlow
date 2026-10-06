"""Idempotent reference data for the single operator, profiles, and settings."""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.logging import configure_logging
from app.models import AppSettings, Profile, ProfileKeyword, User
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)

# Keywords are stored normalized. The profile name is added as a keyword in seed().
PROFILE_SEEDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Software Engineer", ("software engineer", "swe")),
    ("Full Stack Engineer", ("full stack", "fullstack", "full-stack", "mern")),
    ("Frontend Engineer", ("frontend", "front end", "front-end", "react", "react developer", "ui engineer")),
    ("Backend Engineer", ("backend", "back end", "back-end", "node", "nodejs", "django", "api engineer")),
    (
        "AI/ML Engineer",
        (
            "ai/ml",
            "ai engineer",
            "ml engineer",
            "machine learning",
            "machine learning engineer",
            "deep learning",
        ),
    ),
    (
        "Applied AI Engineer",
        ("applied ai", "genai", "gen ai", "generative ai", "llm", "llm engineer"),
    ),
    ("Data Scientist", ("data scientist", "data science")),
)


@dataclass(frozen=True)
class SeedResult:
    user_created: bool
    profiles_created: int
    keywords_created: int
    settings_created: bool


def keywords_for(name: str, keywords: tuple[str, ...]) -> set[str]:
    normalized = {normalize_text(name)}
    normalized.update(normalize_text(keyword) for keyword in keywords)
    normalized.discard("")
    return normalized


def seed(session: Session) -> SeedResult:
    user = session.scalar(select(User).limit(1))
    user_created = user is None
    if user is None:
        user = User(display_name="Operator")
        session.add(user)
        session.flush()

    profiles_created = 0
    keywords_created = 0
    for name, raw_keywords in PROFILE_SEEDS:
        profile = session.scalar(select(Profile).where(Profile.name == name))
        if profile is None:
            profile = Profile(name=name, is_active=True, priority=0)
            session.add(profile)
            session.flush()
            profiles_created += 1

        existing = set(
            session.scalars(select(ProfileKeyword.keyword).where(ProfileKeyword.profile_id == profile.id)).all()
        )
        for keyword in sorted(keywords_for(name, raw_keywords) - existing):
            session.add(ProfileKeyword(profile_id=profile.id, keyword=keyword))
            keywords_created += 1

    settings_row = session.get(AppSettings, 1)
    settings_created = settings_row is None
    if settings_row is None:
        session.add(AppSettings(id=1))

    session.flush()
    return SeedResult(
        user_created=user_created,
        profiles_created=profiles_created,
        keywords_created=keywords_created,
        settings_created=settings_created,
    )


def counts(session: Session) -> dict[str, int]:
    return {
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "profiles": session.scalar(select(func.count()).select_from(Profile)) or 0,
        "keywords": session.scalar(select(func.count()).select_from(ProfileKeyword)) or 0,
        "settings": session.scalar(select(func.count()).select_from(AppSettings)) or 0,
    }


def main() -> None:
    configure_logging()
    with SessionLocal() as session:
        result = seed(session)
        session.commit()
    logger.info(
        "seed committed user_created=%s profiles_created=%s keywords_created=%s settings_created=%s",
        result.user_created,
        result.profiles_created,
        result.keywords_created,
        result.settings_created,
    )


if __name__ == "__main__":
    main()
