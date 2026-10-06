from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.errors import AppError, not_found
from app.models import Profile, ProfileKeyword
from app.schemas.profile import KeywordReplace, ProfileCreate, ProfileOut, ProfileUpdate
from app.services.catalog_common import ensure_optional_resume, ensure_optional_template, require_profile
from app.services.keywords import ensure_keywords_available, keyword_set
from app.utils.text import normalize_text


def _out(profile: Profile, keywords: list[str]) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        name=profile.name,
        resume_id=profile.resume_id,
        email_template_id=profile.email_template_id,
        is_active=profile.is_active,
        priority=profile.priority,
        keywords=keywords,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _load_keywords(session: Session, profile_id: UUID) -> list[str]:
    rows = session.scalars(
        select(ProfileKeyword.keyword).where(ProfileKeyword.profile_id == profile_id).order_by(ProfileKeyword.keyword)
    ).all()
    return list(rows)


def _name_taken(session: Session, name: str, profile_id: UUID | None) -> None:
    statement = select(Profile.id).where(Profile.name == name)
    if profile_id is not None:
        statement = statement.where(Profile.id != profile_id)
    if session.scalar(statement) is not None:
        raise AppError(409, "name_taken", "A profile with that name already exists")


def list_profiles(session: Session, *, limit: int, offset: int) -> tuple[list[ProfileOut], int]:
    total = session.scalar(select(func.count()).select_from(Profile)) or 0
    rows = session.scalars(
        select(Profile).options(selectinload(Profile.keywords)).order_by(Profile.name).limit(limit).offset(offset)
    ).all()
    items = [_out(row, sorted(keyword.keyword for keyword in row.keywords)) for row in rows]
    return items, total


def get_profile(session: Session, profile_id: UUID) -> ProfileOut:
    profile = session.scalar(select(Profile).options(selectinload(Profile.keywords)).where(Profile.id == profile_id))
    if profile is None:
        raise not_found("Profile")
    return _out(profile, sorted(keyword.keyword for keyword in profile.keywords))


def create_profile(session: Session, body: ProfileCreate) -> ProfileOut:
    name = body.name.strip()
    keywords = keyword_set(name, body.keywords)
    _name_taken(session, name, None)
    ensure_optional_resume(session, body.resume_id)
    ensure_optional_template(session, body.email_template_id)
    if body.is_active:
        ensure_keywords_available(session, keywords, None)
    profile = Profile(
        name=name,
        resume_id=body.resume_id,
        email_template_id=body.email_template_id,
        is_active=body.is_active,
        priority=body.priority,
    )
    session.add(profile)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError(409, "name_taken", "A profile with that name already exists") from exc
    for keyword in keywords:
        session.add(ProfileKeyword(profile_id=profile.id, keyword=keyword))
    session.flush()
    session.refresh(profile)
    return _out(profile, keywords)


def update_profile(session: Session, profile_id: UUID, body: ProfileUpdate) -> ProfileOut:
    profile = require_profile(session, profile_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        name = str(changes["name"]).strip()
        new_name = normalize_text(name)
        if new_name == "":
            raise AppError(422, "invalid_name", "Name must contain a letter or number")
        _name_taken(session, name, profile.id)
        old_name = normalize_text(profile.name)
        profile.name = name
        if old_name != new_name:
            session.execute(
                delete(ProfileKeyword).where(
                    ProfileKeyword.profile_id == profile.id,
                    ProfileKeyword.keyword == old_name,
                )
            )
            existing = set(_load_keywords(session, profile.id))
            if new_name not in existing:
                session.add(ProfileKeyword(profile_id=profile.id, keyword=new_name))
            session.flush()
    if "resume_id" in changes:
        ensure_optional_resume(session, changes["resume_id"])
        profile.resume_id = changes["resume_id"]
    if "email_template_id" in changes:
        ensure_optional_template(session, changes["email_template_id"])
        profile.email_template_id = changes["email_template_id"]
    if "priority" in changes:
        profile.priority = changes["priority"]
    if "is_active" in changes:
        profile.is_active = changes["is_active"]
    if profile.is_active:
        ensure_keywords_available(session, _load_keywords(session, profile.id), profile.id)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError(409, "name_taken", "A profile with that name already exists") from exc
    session.refresh(profile)
    return _out(profile, _load_keywords(session, profile.id))


def replace_keywords(session: Session, profile_id: UUID, body: KeywordReplace) -> ProfileOut:
    profile = require_profile(session, profile_id)
    keywords = keyword_set(profile.name, body.keywords)
    if profile.is_active:
        ensure_keywords_available(session, keywords, profile.id)
    session.execute(delete(ProfileKeyword).where(ProfileKeyword.profile_id == profile.id))
    session.flush()
    for keyword in keywords:
        session.add(ProfileKeyword(profile_id=profile.id, keyword=keyword))
    session.flush()
    session.refresh(profile)
    return _out(profile, keywords)


def deactivate_profile(session: Session, profile_id: UUID) -> ProfileOut:
    profile = require_profile(session, profile_id)
    profile.is_active = False
    session.flush()
    session.refresh(profile)
    return _out(profile, _load_keywords(session, profile.id))
