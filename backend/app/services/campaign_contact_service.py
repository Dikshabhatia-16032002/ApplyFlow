"""Read campaign rows and apply a manual profile, resume, or template choice."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import AppError, not_found
from app.integrations.sheets_client import SheetsError, StatusWrite, get_sheets_client
from app.models import Campaign, CampaignContact, Contact, EmailTemplate, Profile, Resume, SheetConnection
from app.schemas.campaign import CampaignContactOut, CampaignOut, ContactMatchUpdate
from app.schemas.common import Page
from app.services.catalog_common import require_profile, require_resume, require_template
from app.services.match_resolution import load_match_context, resolve_manual


def list_campaigns(session: Session, *, limit: int, offset: int) -> Page[CampaignOut]:
    total = session.scalar(select(func.count()).select_from(Campaign)) or 0
    rows = session.scalars(select(Campaign).order_by(Campaign.created_at.desc()).limit(limit).offset(offset)).all()
    return Page(
        items=[CampaignOut(id=row.id, name=row.name, status=row.status, created_at=row.created_at) for row in rows],
        limit=limit,
        offset=offset,
        total=total,
    )


def list_contacts(session: Session, campaign_id: UUID, *, limit: int, offset: int) -> Page[CampaignContactOut]:
    _require_campaign(session, campaign_id)
    total = session.scalar(
        select(func.count()).select_from(CampaignContact).where(CampaignContact.campaign_id == campaign_id)
    ) or 0
    rows = session.execute(_contact_query(campaign_id).limit(limit).offset(offset)).all()
    return Page(items=[_out(*row) for row in rows], limit=limit, offset=offset, total=total)


def update_match(session: Session, campaign_id: UUID, row_id: UUID, body: ContactMatchUpdate) -> CampaignContactOut:
    campaign = _require_campaign(session, campaign_id)
    if campaign.status != "DRAFT":
        raise AppError(409, "campaign_not_draft", "Profile changes apply to a draft run")
    row = session.get(CampaignContact, row_id)
    if row is None or row.campaign_id != campaign_id:
        raise not_found("Contact")
    if row.status not in {"PENDING", "NEEDS_REVIEW"}:
        raise AppError(409, "contact_not_editable", "Only a review or pending row can be changed")

    fields = body.model_fields_set
    if not fields:
        raise AppError(422, "empty_update", "Choose a profile, resume, or template")
    if "profile_id" in fields and body.profile_id is None:
        raise AppError(422, "profile_required", "Choose a profile")
    if "resume_id" in fields and body.resume_id is None:
        raise AppError(422, "resume_required", "Choose a resume")
    if "template_id" in fields and body.template_id is None:
        raise AppError(422, "template_required", "Choose a template")

    if body.resume_id is not None:
        resume = _active_resume(session, body.resume_id)
        row.resume_id = resume.id
        row.resume_overridden = True
    if body.template_id is not None:
        template = _active_template(session, body.template_id)
        row.template_id = template.id
        row.template_overridden = True

    if body.profile_id is not None:
        profile = require_profile(session, body.profile_id)
        if not profile.is_active:
            raise AppError(409, "profile_inactive", "Choose an active profile")
        resolved = resolve_manual(
            load_match_context(session),
            profile.id,
            resume_overridden=row.resume_overridden,
            template_overridden=row.template_overridden,
            resume_id=row.resume_id,
            template_id=row.template_id,
        )
        row.profile_id = resolved.profile_id
        row.match_confidence = resolved.confidence
        row.match_method = "manual"
        row.matched_keywords = list(resolved.matched_keywords)
        if not row.resume_overridden:
            row.resume_id = resolved.resume_id
        if not row.template_overridden:
            row.template_id = resolved.template_id
        row.status = resolved.status
        row.skip_reason = resolved.reason
    else:
        _refresh_status(row)

    _write_sheet(session, campaign, row)
    session.flush()
    loaded = session.execute(_contact_query(campaign_id).where(CampaignContact.id == row.id)).one()
    return _out(*loaded)


def _refresh_status(row: CampaignContact) -> None:
    if row.profile_id is None:
        row.status = "NEEDS_REVIEW"
        row.skip_reason = "ambiguous" if row.skip_reason == "ambiguous" else "needs_review"
        return
    if row.resume_id is None:
        row.status = "NEEDS_REVIEW"
        row.skip_reason = "missing_resume"
        return
    if row.template_id is None:
        row.status = "NEEDS_REVIEW"
        row.skip_reason = "missing_template"
        return
    row.status = "PENDING"
    row.skip_reason = None


def _write_sheet(session: Session, campaign: Campaign, row: CampaignContact) -> None:
    connection = session.get(SheetConnection, campaign.sheet_connection_id)
    if connection is None:
        row.sheet_write_pending = True
        return
    profile = session.get(Profile, row.profile_id) if row.profile_id is not None else None
    resume = session.get(Resume, row.resume_id) if row.resume_id is not None else None
    template = session.get(EmailTemplate, row.template_id) if row.template_id is not None else None
    reason = row.skip_reason or ""
    if row.status == "PENDING":
        reason = ""
    try:
        get_sheets_client().write_status_cells(
            connection.spreadsheet_id,
            connection.sheet_name,
            [
                StatusWrite(
                    sheet_row=row.sheet_row,
                    values={
                        "outreach_status": "NOT_SENT",
                        "sent_at": "",
                        "detected_profile": profile.name if profile is not None else "",
                        "resume_name": resume.name if resume is not None else "",
                        "template_name": template.name if template is not None else "",
                        "outreach_error": reason,
                    },
                )
            ],
        )
    except SheetsError:
        row.sheet_write_pending = True
        return
    row.sheet_write_pending = False


def _active_resume(session: Session, resume_id: UUID) -> Resume:
    resume = require_resume(session, resume_id)
    if not resume.is_active:
        raise AppError(409, "resume_inactive", "Choose an active resume")
    return resume


def _active_template(session: Session, template_id: UUID) -> EmailTemplate:
    template = require_template(session, template_id)
    if not template.is_active:
        raise AppError(409, "template_inactive", "Choose an active template")
    return template


def _require_campaign(session: Session, campaign_id: UUID) -> Campaign:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise not_found("Campaign")
    return campaign


def _contact_query(campaign_id: UUID):
    return (
        select(
            CampaignContact,
            Contact.email,
            Profile.name,
            Resume.name,
            EmailTemplate.name,
        )
        .join(Contact, Contact.id == CampaignContact.contact_id)
        .outerjoin(Profile, Profile.id == CampaignContact.profile_id)
        .outerjoin(Resume, Resume.id == CampaignContact.resume_id)
        .outerjoin(EmailTemplate, EmailTemplate.id == CampaignContact.template_id)
        .where(CampaignContact.campaign_id == campaign_id)
        .order_by(CampaignContact.sheet_row, CampaignContact.id)
    )


def _out(
    row: CampaignContact,
    email: str,
    profile_name: str | None,
    resume_name: str | None,
    template_name: str | None,
) -> CampaignContactOut:
    return CampaignContactOut(
        id=row.id,
        email=email,
        name=row.name,
        company=row.company,
        role=row.role,
        original_role=row.original_role,
        status=row.status,
        skip_reason=row.skip_reason,
        profile_id=row.profile_id,
        profile_name=profile_name,
        match_confidence=row.match_confidence,
        match_method=row.match_method,
        matched_keywords=[str(keyword) for keyword in row.matched_keywords],
        resume_id=row.resume_id,
        resume_name=resume_name,
        template_id=row.template_id,
        template_name=template_name,
        resume_overridden=row.resume_overridden,
        template_overridden=row.template_overridden,
    )
