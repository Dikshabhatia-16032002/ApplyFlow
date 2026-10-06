"""Claim one due job, send or dry-run it, and write the sheet row."""

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import get_settings
from app.integrations.gmail_client import GmailClient, GmailError, OutboundMessage
from app.integrations.sheets_client import SheetsClient, SheetsError, StatusWrite
from app.models import (
    AppSettings,
    Campaign,
    CampaignContact,
    Contact,
    EmailAttempt,
    EmailHistory,
    EmailJob,
    EmailTemplate,
    Profile,
    Resume,
    SheetConnection,
)
from app.services.resume_service import resume_file
from app.services.sheet_headers import clip_cell, valid_email
from app.services.template_render import render_message

logger = logging.getLogger(__name__)

_SUCCESS_OUTCOMES = ("sent", "dry_run")
_STALE_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class DispatchResult:
    action: str
    job_id: UUID | None = None


def backoff_seconds(attempt_count: int, jitter: float = 0) -> float:
    """Wait after a failed try. Attempt 1 waits 60s, attempt 2 waits 120s."""
    return (60 * (2 ** (attempt_count - 1))) + jitter


def dispatch_once(
    session: Session,
    *,
    worker_id: str,
    gmail: GmailClient,
    sheets: SheetsClient,
    now: datetime | None = None,
    jitter_seconds: Callable[[], float] | None = None,
) -> DispatchResult:
    moment = now or datetime.now(UTC)
    jitter = jitter_seconds if jitter_seconds is not None else _default_jitter
    _retry_pending_sheet_writes(session, sheets)
    session.commit()

    settings_row = session.get(AppSettings, 1)
    if settings_row is None or not _running(session):
        return DispatchResult("idle")
    if _over_cap(session, settings_row, moment) or _waiting_for_gap(session, settings_row, moment):
        return DispatchResult("limited")

    job = _claim(session, moment, worker_id)
    if job is None:
        return DispatchResult("idle")
    job_id = job.id
    session.commit()
    result = _send_claimed(session, job_id, worker_id, gmail, sheets, moment, jitter)
    session.commit()
    return result


def recover_stale_sends(session: Session, *, sheets: SheetsClient, now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    cutoff = moment - _STALE_AFTER
    jobs = session.scalars(
        select(EmailJob)
        .where(EmailJob.status == "SENDING", EmailJob.locked_at.is_not(None), EmailJob.locked_at < cutoff)
        .with_for_update(skip_locked=True)
    ).all()
    recovered = 0
    for job in jobs:
        row = session.get(CampaignContact, job.campaign_contact_id)
        if job.gmail_message_id:
            _mark_sent(session, job, row, sheets, moment)
        else:
            job.attempt_count += 1
            job.status = "QUEUED"
            job.locked_at = None
            job.locked_by = None
            if row is not None:
                row.status = "QUEUED"
        _complete_if_idle(session, job.campaign_id, moment)
        recovered += 1
    session.commit()
    return recovered


def skip_queued_job(session: Session, job: EmailJob, sheets: SheetsClient, now: datetime, *, reason: str) -> None:
    if job.status != "QUEUED":
        return
    row = session.get(CampaignContact, job.campaign_contact_id)
    contact = session.get(Contact, job.contact_id)
    job.status = "SKIPPED"
    job.locked_at = None
    job.locked_by = None
    if row is not None:
        row.status = "SKIPPED"
        row.skip_reason = reason
    if row is not None and contact is not None:
        _add_history(
            session,
            job,
            contact,
            row,
            status="SKIPPED",
            subject=None,
            skip_reason=reason,
            error_message=None,
            sent_at=None,
        )
        _write_mark(session, sheets, row, outreach_status="NOT_SENT", sent_at="", error=reason)


def _send_claimed(
    session: Session,
    job_id: UUID,
    worker_id: str,
    gmail: GmailClient,
    sheets: SheetsClient,
    now: datetime,
    jitter: Callable[[], float],
) -> DispatchResult:
    job = _owned(session, job_id, worker_id)
    if job is None:
        return DispatchResult("idle")
    stopped = _release_if_stopped(session, job, sheets, now)
    if stopped is not None:
        return stopped
    if job.gmail_message_id:
        return _mark_sent(session, job, _row(session, job), sheets, now)

    row = _row(session, job)
    contact = session.get(Contact, job.contact_id)
    if row is None or contact is None:
        return _fail(session, job, row, sheets, now, code="render_error", detail="Contact row is missing", retryable=False)

    try:
        if _cell_already_sent(session, sheets, row):
            return _mark_sent(session, job, row, sheets, now, from_sheet=True)
    except SheetsError as exc:
        return _retry_or_fail(
            session,
            job,
            row,
            sheets,
            now,
            jitter,
            code="sheet_unavailable",
            detail=exc.detail,
            retryable=True,
        )

    if _history_has_sent(session, contact.id) and not row.allow_resend:
        return _skip(session, job, row, contact, sheets, now, reason="already_sent", subject=None)

    template = session.get(EmailTemplate, row.template_id) if row.template_id is not None else None
    resume = session.get(Resume, row.resume_id) if row.resume_id is not None else None
    if template is None:
        return _fail(session, job, row, sheets, now, code="render_error", detail="Template is missing", retryable=False)
    rendered = render_message(
        template.subject,
        template.body,
        {
            "name": row.name,
            "company": row.company,
            "role": row.role,
            "location": row.location,
            "mobile": row.mobile,
            "linkedin_url": row.linkedin_url,
        },
    )
    if resume is None:
        return _fail(session, job, row, sheets, now, code="missing_attachment", detail="Resume is missing", retryable=False)
    try:
        path, filename = resume_file(session, resume.id)
        pdf = path.read_bytes()
    except (AppError, OSError):
        return _fail(session, job, row, sheets, now, code="missing_attachment", detail="Resume file is missing", retryable=False)
    if not pdf.startswith(b"%PDF"):
        return _fail(session, job, row, sheets, now, code="missing_attachment", detail="Resume file is missing", retryable=False)
    if not valid_email(contact.email):
        return _fail(session, job, row, sheets, now, code="invalid_recipient", detail="Recipient address is invalid", retryable=False)

    stopped = _release_if_stopped(session, job, sheets, now)
    if stopped is not None:
        return stopped

    if job.dry_run or get_settings().dry_run:
        logger.info(
            "Would send:\nTo: %s\nTemplate: %s\nResume: %s\nSubject: %s",
            contact.email,
            template.name,
            filename,
            rendered.subject,
            extra={
                "campaign_id": str(job.campaign_id),
                "contact_id": str(job.contact_id),
                "email_job_id": str(job.id),
            },
        )
        return _finish_dry_run(session, job, row, sheets, now)

    message = OutboundMessage(
        to=contact.email,
        subject=rendered.subject,
        body=rendered.body,
        attachment_filename=filename,
        attachment_bytes=pdf,
    )
    try:
        message_id = gmail.send(message)
    except GmailError as exc:
        if exc.code == "auth":
            return _pause_for_auth(session, job, row, exc.detail)
        return _retry_or_fail(
            session,
            job,
            row,
            sheets,
            now,
            jitter,
            code=exc.code,
            detail=exc.detail,
            retryable=exc.retryable,
        )

    owned = _owned(session, job.id, job.locked_by or "")
    if owned is None:
        return DispatchResult("idle")
    owned.gmail_message_id = message_id
    session.commit()
    owned = _owned(session, job_id, worker_id)
    if owned is None:
        return DispatchResult("sent", job_id)
    return _mark_sent(session, owned, _row(session, owned), sheets, now, subject=rendered.subject)


def _claim(session: Session, now: datetime, worker_id: str) -> EmailJob | None:
    job = session.scalar(
        select(EmailJob)
        .join(Campaign, Campaign.id == EmailJob.campaign_id)
        .where(
            EmailJob.status == "QUEUED",
            or_(EmailJob.next_attempt_at.is_(None), EmailJob.next_attempt_at <= now),
            Campaign.status == "RUNNING",
        )
        .order_by(EmailJob.scheduled_at, EmailJob.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=EmailJob)
    )
    if job is None:
        return None
    job.status = "SENDING"
    job.locked_at = now
    job.locked_by = worker_id
    row = session.get(CampaignContact, job.campaign_contact_id)
    if row is not None:
        row.status = "SENDING"
    session.flush()
    return job


def _release_if_stopped(session: Session, job: EmailJob, sheets: SheetsClient, now: datetime) -> DispatchResult | None:
    campaign = session.get(Campaign, job.campaign_id)
    if campaign is not None and campaign.status == "RUNNING":
        return None
    row = _row(session, job)
    contact = session.get(Contact, job.contact_id)
    if campaign is not None and campaign.status == "CANCELLED" and row is not None and contact is not None:
        return _skip(session, job, row, contact, sheets, now, reason="cancelled", subject=None)
    job.status = "QUEUED"
    job.locked_at = None
    job.locked_by = None
    if row is not None and row.status == "SENDING":
        row.status = "QUEUED"
    return DispatchResult("released", job.id)


def _pause_for_auth(session: Session, job: EmailJob, row: CampaignContact, detail: str) -> DispatchResult:
    job.status = "QUEUED"
    job.locked_at = None
    job.locked_by = None
    job.last_error = detail
    job.last_error_code = "auth"
    job.error_retryable = False
    if row.status == "SENDING":
        row.status = "QUEUED"
    settings_row = session.get(AppSettings, 1)
    if settings_row is not None:
        settings_row.gmail_reconnect_required = True
    running = session.scalars(select(Campaign).where(Campaign.status == "RUNNING")).all()
    for campaign in running:
        campaign.status = "PAUSED"
    return DispatchResult("auth_paused", job.id)


def _finish_dry_run(
    session: Session,
    job: EmailJob,
    row: CampaignContact,
    sheets: SheetsClient,
    now: datetime,
) -> DispatchResult:
    job.status = "SKIPPED"
    job.dry_run = True
    job.gmail_message_id = None
    job.locked_at = None
    job.locked_by = None
    row.status = "SKIPPED"
    row.skip_reason = "dry_run"
    _add_attempt(session, job, outcome="dry_run", error_message=None, error_code=None, now=now)
    _write_mark(session, sheets, row, outreach_status="NOT_SENT", sent_at="", error="dry_run")
    _complete_if_idle(session, job.campaign_id, now)
    return DispatchResult("dry_run", job.id)


def _mark_sent(
    session: Session,
    job: EmailJob,
    row: CampaignContact | None,
    sheets: SheetsClient,
    now: datetime,
    *,
    from_sheet: bool = False,
    subject: str | None = None,
) -> DispatchResult:
    job.status = "SENT"
    job.locked_at = None
    job.locked_by = None
    job.last_error = None
    job.error_retryable = None
    if not from_sheet and job.sent_at is None:
        job.sent_at = now
    if row is not None:
        row.status = "SENT"
        row.skip_reason = None
    if not from_sheet:
        contact = session.get(Contact, job.contact_id)
        if contact is not None and row is not None:
            _add_attempt(session, job, outcome="sent", error_message=None, error_code=None, now=now)
            _add_history(
                session,
                job,
                contact,
                row,
                status="SENT",
                subject=subject,
                skip_reason=None,
                error_message=None,
                sent_at=job.sent_at,
            )
        sent_at = _stamp(job.sent_at) if job.sent_at is not None else _stamp(now)
        if row is not None:
            _write_mark(session, sheets, row, outreach_status="SENT", sent_at=sent_at, error="")
    _complete_if_idle(session, job.campaign_id, now)
    return DispatchResult("sent", job.id)


def _skip(
    session: Session,
    job: EmailJob,
    row: CampaignContact,
    contact: Contact,
    sheets: SheetsClient,
    now: datetime,
    *,
    reason: str,
    subject: str | None,
) -> DispatchResult:
    job.status = "SKIPPED"
    job.locked_at = None
    job.locked_by = None
    row.status = "SKIPPED"
    row.skip_reason = reason
    _add_history(
        session,
        job,
        contact,
        row,
        status="SKIPPED",
        subject=subject,
        skip_reason=reason,
        error_message=None,
        sent_at=None,
    )
    _write_mark(session, sheets, row, outreach_status="NOT_SENT", sent_at="", error=reason)
    _complete_if_idle(session, job.campaign_id, now)
    return DispatchResult("skipped", job.id)


def _fail(
    session: Session,
    job: EmailJob,
    row: CampaignContact | None,
    sheets: SheetsClient,
    now: datetime,
    *,
    code: str,
    detail: str,
    retryable: bool,
) -> DispatchResult:
    job.status = "FAILED"
    job.locked_at = None
    job.locked_by = None
    job.last_error = detail
    job.last_error_code = code
    job.error_retryable = retryable
    if row is not None:
        row.status = "FAILED"
        row.skip_reason = code
    contact = session.get(Contact, job.contact_id)
    _add_attempt(session, job, outcome="failed", error_message=detail, error_code=code, now=now)
    if contact is not None and row is not None:
        _add_history(
            session,
            job,
            contact,
            row,
            status="FAILED",
            subject=None,
            skip_reason=None,
            error_message=detail,
            sent_at=None,
        )
        _write_mark(session, sheets, row, outreach_status="NOT_SENT", sent_at="", error=clip_cell(f"failed: {detail}"))
    _complete_if_idle(session, job.campaign_id, now)
    return DispatchResult("failed", job.id)


def _retry_or_fail(
    session: Session,
    job: EmailJob,
    row: CampaignContact,
    sheets: SheetsClient,
    now: datetime,
    jitter: Callable[[], float],
    *,
    code: str,
    detail: str,
    retryable: bool,
) -> DispatchResult:
    job.attempt_count += 1
    job.last_error = detail
    job.last_error_code = code
    job.error_retryable = retryable
    if not retryable or job.attempt_count >= job.max_attempts:
        return _fail(session, job, row, sheets, now, code=code, detail=detail, retryable=retryable)
    job.status = "QUEUED"
    job.locked_at = None
    job.locked_by = None
    job.next_attempt_at = now + timedelta(seconds=backoff_seconds(job.attempt_count, jitter()))
    if row.status == "SENDING":
        row.status = "QUEUED"
    _add_attempt(session, job, outcome="retry", error_message=detail, error_code=code, now=now)
    return DispatchResult("requeued", job.id)


def _retry_pending_sheet_writes(session: Session, sheets: SheetsClient) -> None:
    rows = session.scalars(
        select(CampaignContact).where(CampaignContact.sheet_write_pending.is_(True)).limit(20)
    ).all()
    for row in rows:
        if row.status == "SENT":
            job = session.scalar(select(EmailJob).where(EmailJob.campaign_contact_id == row.id))
            sent_at = _stamp(job.sent_at) if job is not None and job.sent_at is not None else ""
            _write_mark(session, sheets, row, outreach_status="SENT", sent_at=sent_at, error="")
            continue
        if row.status == "FAILED":
            job = session.scalar(select(EmailJob).where(EmailJob.campaign_contact_id == row.id))
            detail = job.last_error if job is not None and job.last_error else "send failed"
            _write_mark(session, sheets, row, outreach_status="NOT_SENT", sent_at="", error=clip_cell(f"failed: {detail}"))
            continue
        if row.status == "SKIPPED":
            _write_mark(session, sheets, row, outreach_status="NOT_SENT", sent_at="", error=row.skip_reason or "")


def _cell_already_sent(session: Session, sheets: SheetsClient, row: CampaignContact) -> bool:
    campaign = session.get(Campaign, row.campaign_id)
    if campaign is None:
        return False
    connection = session.get(SheetConnection, campaign.sheet_connection_id)
    if connection is None:
        return False
    grid = sheets.read_tab(connection.spreadsheet_id, connection.sheet_name)
    column = _status_column(connection.status_columns, "outreach_status")
    if column is None:
        return False
    index = row.sheet_row - 2
    if index < 0 or index >= len(grid.rows):
        return False
    cells = grid.rows[index]
    if cells is None or column >= len(cells):
        return False
    return cells[column].strip().upper() == "SENT"


def _write_mark(
    session: Session,
    sheets: SheetsClient,
    row: CampaignContact,
    *,
    outreach_status: str,
    sent_at: str,
    error: str,
) -> None:
    campaign = session.get(Campaign, row.campaign_id)
    connection = session.get(SheetConnection, campaign.sheet_connection_id) if campaign is not None else None
    if connection is None:
        row.sheet_write_pending = True
        return
    profile = session.get(Profile, row.profile_id) if row.profile_id is not None else None
    resume = session.get(Resume, row.resume_id) if row.resume_id is not None else None
    template = session.get(EmailTemplate, row.template_id) if row.template_id is not None else None
    try:
        sheets.write_status_cells(
            connection.spreadsheet_id,
            connection.sheet_name,
            [
                StatusWrite(
                    sheet_row=row.sheet_row,
                    values={
                        "outreach_status": outreach_status,
                        "sent_at": sent_at,
                        "detected_profile": profile.name if profile is not None else "",
                        "resume_name": resume.name if resume is not None else "",
                        "template_name": template.name if template is not None else "",
                        "outreach_error": error,
                    },
                )
            ],
        )
    except SheetsError:
        row.sheet_write_pending = True
        return
    row.sheet_write_pending = False


def _complete_if_idle(session: Session, campaign_id: UUID, now: datetime) -> None:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None or campaign.status != "RUNNING":
        return
    session.flush()
    pending = session.scalar(
        select(func.count())
        .select_from(EmailJob)
        .where(EmailJob.campaign_id == campaign_id, EmailJob.status.in_(("QUEUED", "SENDING")))
    ) or 0
    if pending == 0:
        campaign.status = "COMPLETED"
        campaign.completed_at = now


def _add_attempt(
    session: Session,
    job: EmailJob,
    *,
    outcome: str,
    error_message: str | None,
    error_code: str | None,
    now: datetime,
) -> None:
    if outcome == "sent":
        existing = session.scalar(
            select(EmailAttempt.id).where(EmailAttempt.email_job_id == job.id, EmailAttempt.outcome == "sent").limit(1)
        )
        if existing is not None:
            return
    session.add(
        EmailAttempt(
            email_job_id=job.id,
            attempted_at=now,
            outcome=outcome,
            error_message=error_message,
            error_code=error_code,
        )
    )


def _add_history(
    session: Session,
    job: EmailJob,
    contact: Contact,
    row: CampaignContact,
    *,
    status: str,
    subject: str | None,
    skip_reason: str | None,
    error_message: str | None,
    sent_at: datetime | None,
) -> None:
    existing = session.scalar(select(EmailHistory.id).where(EmailHistory.email_job_id == job.id).limit(1))
    if existing is not None:
        return
    session.add(
        EmailHistory(
            email_job_id=job.id,
            contact_id=contact.id,
            campaign_id=job.campaign_id,
            recipient_email=contact.email,
            profile_id=row.profile_id,
            resume_id=row.resume_id,
            template_id=row.template_id,
            subject=subject,
            status=status,
            skip_reason=skip_reason,
            error_message=error_message,
            dry_run=False,
            sent_at=sent_at,
        )
    )


def _history_has_sent(session: Session, contact_id: UUID) -> bool:
    found = session.scalar(
        select(EmailHistory.id).where(EmailHistory.contact_id == contact_id, EmailHistory.status == "SENT").limit(1)
    )
    return found is not None


def _running(session: Session) -> bool:
    found = session.scalar(select(Campaign.id).where(Campaign.status == "RUNNING").limit(1))
    return found is not None


def _over_cap(session: Session, settings_row: AppSettings, now: datetime) -> bool:
    hour_ago = now - timedelta(minutes=60)
    hourly = _success_count(session, hour_ago)
    if hourly >= settings_row.emails_per_hour:
        return True
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return _success_count(session, day_start) >= settings_row.max_daily_emails


def _waiting_for_gap(session: Session, settings_row: AppSettings, now: datetime) -> bool:
    last = session.scalar(
        select(func.max(EmailAttempt.attempted_at)).where(EmailAttempt.outcome.in_(_SUCCESS_OUTCOMES))
    )
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return now < last + timedelta(seconds=settings_row.delay_between_emails_seconds)


def _success_count(session: Session, since: datetime) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(EmailAttempt)
            .where(EmailAttempt.outcome.in_(_SUCCESS_OUTCOMES), EmailAttempt.attempted_at >= since)
        )
        or 0
    )


def _owned(session: Session, job_id: UUID, worker_id: str) -> EmailJob | None:
    job = session.get(EmailJob, job_id)
    if job is None or job.status != "SENDING" or job.locked_by != worker_id:
        return None
    return job


def _row(session: Session, job: EmailJob) -> CampaignContact | None:
    return session.get(CampaignContact, job.campaign_contact_id)


def _status_column(indexes: dict | None, name: str) -> int | None:
    if not indexes:
        return None
    value = indexes.get(name)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_jitter() -> float:
    return random.uniform(0, 5)
