"""Confirm a draft and move a run between ready, running, paused, and cancelled."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import AppError, not_found
from app.config import get_settings
from app.integrations.sheets_client import SheetsClient, get_sheets_client
from app.models import AppSettings, Campaign, CampaignContact, EmailJob
from app.schemas.campaign import CampaignOut
from app.services.email_service import skip_queued_job


def confirm_campaign(session: Session, campaign_id: UUID) -> CampaignOut:
    campaign = _locked(session, campaign_id)
    if campaign.status != "DRAFT":
        raise AppError(409, "campaign_not_draft", "Only a draft run can be confirmed")
    rows = session.scalars(select(CampaignContact).where(CampaignContact.campaign_id == campaign.id)).all()
    for row in rows:
        if row.status == "SKIPPED" or row.status == "SENT":
            continue
        if row.status == "NEEDS_REVIEW" or row.resume_id is None or row.template_id is None:
            raise AppError(409, "needs_review", "Resolve every included row before confirming")
    campaign.status = "READY"
    campaign.confirmed_at = datetime.now(UTC)
    session.flush()
    return _out(campaign)


def start_campaign(session: Session, campaign_id: UUID) -> CampaignOut:
    campaign = _locked(session, campaign_id)
    if campaign.status != "READY":
        raise AppError(409, "campaign_not_ready", "Confirm the run before starting")
    settings_row = session.get(AppSettings, 1)
    delay = settings_row.delay_between_emails_seconds if settings_row is not None else 60
    max_attempts = settings_row.max_attempts if settings_row is not None else 3
    dry_run = get_settings().dry_run
    now = datetime.now(UTC)
    rows = session.scalars(
        select(CampaignContact)
        .where(CampaignContact.campaign_id == campaign.id, CampaignContact.status == "PENDING")
        .order_by(CampaignContact.sheet_row, CampaignContact.id)
    ).all()
    for index, row in enumerate(rows):
        existing = session.scalar(select(EmailJob.id).where(EmailJob.campaign_contact_id == row.id))
        due = now + timedelta(seconds=delay * index)
        if existing is None:
            session.add(
                EmailJob(
                    campaign_contact_id=row.id,
                    campaign_id=campaign.id,
                    contact_id=row.contact_id,
                    status="QUEUED",
                    scheduled_at=due,
                    next_attempt_at=due,
                    max_attempts=max_attempts,
                    dry_run=dry_run,
                )
            )
        row.status = "QUEUED"
    campaign.status = "RUNNING"
    campaign.started_at = now
    session.flush()
    return _out(campaign)


def pause_campaign(session: Session, campaign_id: UUID) -> CampaignOut:
    campaign = _locked(session, campaign_id)
    if campaign.status != "RUNNING":
        raise AppError(409, "campaign_not_running", "Only a running run can be paused")
    campaign.status = "PAUSED"
    session.flush()
    return _out(campaign)


def resume_campaign(session: Session, campaign_id: UUID) -> CampaignOut:
    campaign = _locked(session, campaign_id)
    if campaign.status != "PAUSED":
        raise AppError(409, "campaign_not_paused", "Only a paused run can resume")
    campaign.status = "RUNNING"
    session.flush()
    return _out(campaign)


def cancel_campaign(session: Session, campaign_id: UUID, sheets: SheetsClient | None = None) -> CampaignOut:
    campaign = _locked(session, campaign_id)
    if campaign.status not in {"READY", "RUNNING", "PAUSED"}:
        raise AppError(409, "campaign_not_active", "This run cannot be cancelled")
    client = sheets if sheets is not None else get_sheets_client()
    now = datetime.now(UTC)
    jobs = session.scalars(
        select(EmailJob).where(EmailJob.campaign_id == campaign.id, EmailJob.status == "QUEUED")
    ).all()
    for job in jobs:
        skip_queued_job(session, job, client, now, reason="cancelled")
    campaign.status = "CANCELLED"
    campaign.cancelled_at = now
    session.flush()
    return _out(campaign)


def _locked(session: Session, campaign_id: UUID) -> Campaign:
    campaign = session.get(Campaign, campaign_id, with_for_update=True)
    if campaign is None:
        raise not_found("Campaign")
    return campaign


def _out(campaign: Campaign) -> CampaignOut:
    return CampaignOut(id=campaign.id, name=campaign.name, status=campaign.status, created_at=campaign.created_at)
