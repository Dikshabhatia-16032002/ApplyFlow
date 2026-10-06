from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import AppError, not_found
from app.models import EmailTemplate, Profile, Resume


def raise_integrity(exc: IntegrityError, *, name_message: str) -> None:
    text = str(getattr(exc, "orig", exc)).lower()
    if "name" in text:
        raise AppError(409, "name_taken", name_message) from exc
    if "default" in text:
        raise AppError(409, "default_conflict", "Another item is already the default") from exc
    raise AppError(409, "conflict", "The save conflicts with existing data") from exc


def require_profile(session: Session, profile_id: UUID) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise not_found("Profile")
    return profile


def require_resume(session: Session, resume_id: UUID) -> Resume:
    resume = session.get(Resume, resume_id)
    if resume is None:
        raise not_found("Resume")
    return resume


def require_template(session: Session, template_id: UUID) -> EmailTemplate:
    template = session.get(EmailTemplate, template_id)
    if template is None:
        raise not_found("Template")
    return template


def ensure_optional_resume(session: Session, resume_id: UUID | None) -> None:
    if resume_id is not None:
        require_resume(session, resume_id)


def ensure_optional_template(session: Session, template_id: UUID | None) -> None:
    if template_id is not None:
        require_template(session, template_id)


def apply_active_and_default(
    session: Session,
    model: type[Resume] | type[EmailTemplate],
    row: Resume | EmailTemplate,
    *,
    is_active: bool | None,
    is_default: bool | None,
    noun: str,
) -> None:
    if is_active is None and is_default is None:
        return
    next_active = row.is_active if is_active is None else is_active
    if is_default is True and not next_active:
        raise AppError(409, "inactive_default", f"An inactive {noun} cannot be the default")
    row.is_active = next_active
    if not next_active:
        row.is_default = False
        return
    if is_default is True:
        session.execute(update(model).where(model.id != row.id, model.is_default.is_(True)).values(is_default=False))
        session.flush()
        row.is_default = True
    elif is_default is False:
        row.is_default = False


def assign_profiles(session: Session, *, column: str, owner_id: UUID, profile_ids: list[UUID]) -> None:
    wanted = list(dict.fromkeys(profile_ids))
    found = session.scalars(select(Profile).where(Profile.id.in_(wanted))).all() if wanted else []
    if len(found) != len(wanted):
        raise not_found("Profile")
    current = session.scalars(select(Profile).where(getattr(Profile, column) == owner_id)).all()
    wanted_ids = set(wanted)
    for profile in current:
        if profile.id not in wanted_ids:
            setattr(profile, column, None)
    for profile in found:
        setattr(profile, column, owner_id)


def profile_ids_for(session: Session, column: str, owner_id: UUID) -> list[UUID]:
    rows = session.scalars(select(Profile).where(getattr(Profile, column) == owner_id).order_by(Profile.name)).all()
    return [row.id for row in rows]
