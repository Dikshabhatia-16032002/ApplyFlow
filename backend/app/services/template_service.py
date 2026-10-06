from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.models import EmailTemplate
from app.schemas.template import TemplateCreate, TemplateOut, TemplatePreviewOut, TemplatePreviewRequest, TemplateUpdate
from app.services.catalog_common import (
    apply_active_and_default,
    assign_profiles,
    profile_ids_for,
    raise_integrity,
    require_template,
)
from app.services.template_render import render_message


def _out(session: Session, template: EmailTemplate) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        subject=template.subject,
        body=template.body,
        is_active=template.is_active,
        is_default=template.is_default,
        profile_ids=profile_ids_for(session, "email_template_id", template.id),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def list_templates(session: Session, *, limit: int, offset: int) -> tuple[list[TemplateOut], int]:
    total = session.scalar(select(func.count()).select_from(EmailTemplate)) or 0
    rows = session.scalars(select(EmailTemplate).order_by(EmailTemplate.name).limit(limit).offset(offset)).all()
    return [_out(session, row) for row in rows], total


def get_template(session: Session, template_id: UUID) -> TemplateOut:
    return _out(session, require_template(session, template_id))


def create_template(session: Session, body: TemplateCreate) -> TemplateOut:
    name = _clean_name(body.name)
    subject = _clean_subject(body.subject)
    if body.is_default and not body.is_active:
        raise AppError(409, "inactive_default", "An inactive template cannot be the default")
    template = EmailTemplate(
        name=name,
        subject=subject,
        body=body.body,
        is_active=body.is_active,
        is_default=False,
    )
    session.add(template)
    try:
        session.flush()
        if body.profile_ids:
            assign_profiles(session, column="email_template_id", owner_id=template.id, profile_ids=body.profile_ids)
        apply_active_and_default(
            session,
            EmailTemplate,
            template,
            is_active=body.is_active,
            is_default=body.is_default,
            noun="template",
        )
        session.flush()
    except IntegrityError as exc:
        raise_integrity(exc, name_message="A template with that name already exists")
    session.refresh(template)
    return _out(session, template)


def update_template(session: Session, template_id: UUID, body: TemplateUpdate) -> TemplateOut:
    template = require_template(session, template_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        template.name = _clean_name(str(changes["name"]))
    if "subject" in changes:
        template.subject = _clean_subject(str(changes["subject"]))
    if "body" in changes:
        template.body = changes["body"]
    apply_active_and_default(
        session,
        EmailTemplate,
        template,
        is_active=changes["is_active"] if "is_active" in changes else None,
        is_default=changes["is_default"] if "is_default" in changes else None,
        noun="template",
    )
    if "profile_ids" in changes:
        assign_profiles(session, column="email_template_id", owner_id=template.id, profile_ids=changes["profile_ids"])
    try:
        session.flush()
    except IntegrityError as exc:
        raise_integrity(exc, name_message="A template with that name already exists")
    session.refresh(template)
    return _out(session, template)


def deactivate_template(session: Session, template_id: UUID) -> TemplateOut:
    template = require_template(session, template_id)
    template.is_active = False
    template.is_default = False
    session.flush()
    session.refresh(template)
    return _out(session, template)


def duplicate_template(session: Session, template_id: UUID) -> TemplateOut:
    source = require_template(session, template_id)
    copy = EmailTemplate(
        name=_copy_name(session, source.name),
        subject=source.subject,
        body=source.body,
        is_active=True,
        is_default=False,
    )
    session.add(copy)
    try:
        session.flush()
    except IntegrityError as exc:
        raise_integrity(exc, name_message="A template with that name already exists")
    session.refresh(copy)
    return _out(session, copy)


def preview_template(session: Session, body: TemplatePreviewRequest) -> TemplatePreviewOut:
    subject = body.subject
    text = body.body
    if body.template_id is not None:
        template = require_template(session, body.template_id)
        if subject is None:
            subject = template.subject
        if text is None:
            text = template.body
    if subject is None or text is None:
        raise AppError(422, "preview_source_required", "Provide a subject and body, or a template_id")
    rendered = render_message(
        subject,
        text,
        {
            "name": body.name,
            "company": body.company,
            "role": body.role,
            "location": body.location,
            "mobile": body.mobile,
            "linkedin_url": body.linkedin_url,
        },
    )
    return TemplatePreviewOut(
        subject=rendered.subject,
        body=rendered.body,
        empty_variables=rendered.empty_variables,
        unknown_tokens=rendered.unknown_tokens,
    )


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise AppError(422, "invalid_name", "Name is required")
    return name


def _clean_subject(value: str) -> str:
    subject = value.strip()
    if not subject:
        raise AppError(422, "invalid_subject", "Subject is required")
    return subject


def _copy_name(session: Session, original: str) -> str:
    base = f"Copy of {original}".strip()
    if len(base) > 200:
        base = base[:200].rstrip()
    candidate = base
    number = 2
    while session.scalar(select(EmailTemplate.id).where(EmailTemplate.name == candidate)) is not None:
        suffix = f" ({number})"
        candidate = f"{base[: 200 - len(suffix)].rstrip()}{suffix}"
        number += 1
        if number > 50:
            raise AppError(409, "name_taken", "Could not find a unique copy name")
    return candidate
