from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.models import Profile, ProfileKeyword
from app.utils.text import normalize_text


def keyword_set(name: str, raw_keywords: list[str]) -> list[str]:
    normalized = {normalize_text(name)}
    normalized.update(normalize_text(keyword) for keyword in raw_keywords)
    normalized.discard("")
    if not normalized:
        raise AppError(422, "invalid_name", "Name must contain a letter or number")
    if len(normalized) > 100:
        raise AppError(422, "too_many_keywords", "A profile can have at most 100 keywords")
    if any(len(keyword) > 200 for keyword in normalized):
        raise AppError(422, "keyword_too_long", "Keywords must be 200 characters or fewer")
    return sorted(normalized)


def ensure_keywords_available(session: Session, keywords: list[str], profile_id: UUID | None) -> None:
    statement = (
        select(ProfileKeyword.keyword, Profile.name)
        .join(Profile, Profile.id == ProfileKeyword.profile_id)
        .where(Profile.is_active.is_(True), ProfileKeyword.keyword.in_(keywords))
    )
    if profile_id is not None:
        statement = statement.where(Profile.id != profile_id)
    conflicts = session.execute(statement).all()
    if not conflicts:
        return
    shown = ", ".join(f"{keyword} ({owner})" for keyword, owner in conflicts[:5])
    raise AppError(409, "keyword_conflict", f"Keyword already used by an active profile: {shown}")
