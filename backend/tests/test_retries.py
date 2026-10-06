from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.gmail_client import FakeGmailClient, GmailError
from app.integrations.sheets_client import StatusWrite
from app.models import AppSettings, Campaign, CampaignContact, EmailJob
from app.services.campaign_service import start_campaign
from app.services.email_service import backoff_seconds, dispatch_once, recover_stale_sends

_NO_JITTER = lambda: 0


def test_backoff_is_sixty_then_one_twenty() -> None:
    assert backoff_seconds(1) == 60
    assert backoff_seconds(2) == 120
    assert backoff_seconds(2, jitter=3) == 123


def test_retryable_error_requeues_once(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready()
    gmail = FakeGmailClient()
    gmail.error = GmailError("rate_limit", "Gmail rate limit", retryable=True)
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        moment = datetime.now(UTC)
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            now=moment,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "requeued"
        job = session.get(EmailJob, result.job_id)
        assert job is not None
        assert job.status == "QUEUED"
        assert job.attempt_count == 1
        assert job.gmail_message_id is None
        assert job.next_attempt_at is not None
        wait = job.next_attempt_at - moment
        assert timedelta(seconds=59) <= wait <= timedelta(seconds=61)
        assert len(gmail.sent) == 0

        gmail.error = None
        sent = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            now=moment + timedelta(seconds=60),
            jitter_seconds=_NO_JITTER,
        )
        assert sent.action == "sent"
        assert len(gmail.sent) == 1


def test_attempts_exhausted_fail_the_job(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready()
    gmail = FakeGmailClient()
    gmail.error = GmailError("gmail_unavailable", "Gmail did not respond", retryable=True)
    with SessionLocal() as session:
        settings_row = session.get(AppSettings, 1)
        assert settings_row is not None
        settings_row.max_attempts = 1
        session.commit()
        start_campaign(session, ready.campaign_id)
        session.commit()
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "failed"
        job = session.get(EmailJob, result.job_id)
        assert job is not None
        assert job.status == "FAILED"
        assert job.attempt_count == 1
        row = session.get(CampaignContact, job.campaign_contact_id)
        assert row is not None
        assert row.status == "FAILED"
    grid = mail.fake.read_tab(ready.spreadsheet_id, "Sheet1")
    assert grid.rows[0] is not None
    assert grid.rows[0][4] == "NOT_SENT"
    assert grid.rows[0][9].startswith("failed:")


def test_invalid_recipient_fails_without_a_retry(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready(email="not-an-email")
    gmail = FakeGmailClient()
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "failed"
        job = session.get(EmailJob, result.job_id)
        assert job is not None
        assert job.status == "FAILED"
        assert job.error_retryable is False
        assert job.last_error_code == "invalid_recipient"
        assert job.attempt_count == 0
        assert len(gmail.sent) == 0


def test_existing_gmail_id_does_not_send_again(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready()
    gmail = FakeGmailClient()
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        job = session.scalar(select(EmailJob).where(EmailJob.campaign_id == ready.campaign_id))
        assert job is not None
        job.gmail_message_id = "already-accepted"
        session.commit()
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "sent"
        assert len(gmail.sent) == 0
        refreshed = session.get(EmailJob, job.id)
        assert refreshed is not None
        assert refreshed.status == "SENT"
        assert refreshed.gmail_message_id == "already-accepted"


def test_sheet_cell_already_sent_skips_gmail(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready()
    mail.fake.write_status_cells(
        ready.spreadsheet_id,
        "Sheet1",
        [StatusWrite(sheet_row=2, values={"outreach_status": "SENT"})],
    )
    gmail = FakeGmailClient()
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "sent"
        assert len(gmail.sent) == 0


def test_auth_failure_pauses_the_run(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready()
    gmail = FakeGmailClient()
    gmail.error = GmailError("auth", "Gmail authorization failed", retryable=False)
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "auth_paused"
        campaign = session.get(Campaign, ready.campaign_id)
        assert campaign is not None
        assert campaign.status == "PAUSED"
        job = session.get(EmailJob, result.job_id)
        assert job is not None
        assert job.status == "QUEUED"
        assert job.attempt_count == 0
        settings_row = session.get(AppSettings, 1)
        assert settings_row is not None
        assert settings_row.gmail_reconnect_required is True


def test_stale_lock_without_a_message_id_returns_to_the_queue(mail) -> None:
    ready = mail.ready()
    moment = datetime.now(UTC)
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        job = session.scalar(select(EmailJob).where(EmailJob.campaign_id == ready.campaign_id))
        assert job is not None
        job.status = "SENDING"
        job.locked_at = moment - timedelta(minutes=11)
        job.locked_by = "worker-old"
        row = session.get(CampaignContact, job.campaign_contact_id)
        assert row is not None
        row.status = "SENDING"
        session.commit()
        recovered = recover_stale_sends(session, sheets=mail.fake, now=moment)
        assert recovered == 1
        refreshed = session.get(EmailJob, job.id)
        assert refreshed is not None
        assert refreshed.status == "QUEUED"
        assert refreshed.attempt_count == 1
        assert refreshed.locked_by is None


def test_stale_lock_with_a_message_id_marks_sent(mail) -> None:
    ready = mail.ready()
    moment = datetime.now(UTC)
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        session.commit()
        job = session.scalar(select(EmailJob).where(EmailJob.campaign_id == ready.campaign_id))
        assert job is not None
        job.status = "SENDING"
        job.locked_at = moment - timedelta(minutes=11)
        job.locked_by = "worker-old"
        job.gmail_message_id = "accepted-before-crash"
        session.commit()
        recovered = recover_stale_sends(session, sheets=mail.fake, now=moment)
        assert recovered == 1
        refreshed = session.get(EmailJob, job.id)
        assert refreshed is not None
        assert refreshed.status == "SENT"
        assert refreshed.gmail_message_id == "accepted-before-crash"
    grid = mail.fake.read_tab(ready.spreadsheet_id, "Sheet1")
    assert grid.rows[0] is not None
    assert grid.rows[0][4] == "SENT"
