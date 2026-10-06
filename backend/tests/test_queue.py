import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.gmail_client import FakeGmailClient
from app.models import AppSettings, Campaign, CampaignContact, EmailHistory, EmailJob
from app.services.campaign_service import pause_campaign, start_campaign
from app.services.email_service import dispatch_once

_NO_JITTER = lambda: 0


def test_start_queues_one_job_per_pending_row(mail, client) -> None:
    ready = mail.ready(rows=2)
    with SessionLocal() as session:
        settings_row = session.get(AppSettings, 1)
        assert settings_row is not None
        settings_row.delay_between_emails_seconds = 60
        session.commit()

    first = client.post(f"/api/v1/campaigns/{ready.campaign_id}/start")
    second = client.post(f"/api/v1/campaigns/{ready.campaign_id}/start")
    assert first.status_code == 200
    assert first.json()["status"] == "RUNNING"
    assert second.status_code == 409

    with SessionLocal() as session:
        jobs = session.scalars(select(EmailJob).where(EmailJob.campaign_id == ready.campaign_id).order_by(EmailJob.scheduled_at)).all()
        assert len(jobs) == 2
        assert jobs[0].status == "QUEUED"
        assert jobs[0].dry_run is True
        gap = jobs[1].scheduled_at - jobs[0].scheduled_at
        assert gap == timedelta(seconds=60)
        queued = session.scalar(
            select(func.count()).select_from(CampaignContact).where(
                CampaignContact.campaign_id == ready.campaign_id,
                CampaignContact.status == "QUEUED",
            )
        )
        assert queued == 2


def test_confirm_rejects_unresolved_rows(mail, client) -> None:
    ready = mail.ready(status="NEEDS_REVIEW", campaign_status="DRAFT")
    blocked = client.post(f"/api/v1/campaigns/{ready.campaign_id}/confirm")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "needs_review"

    with SessionLocal() as session:
        row = session.scalar(select(CampaignContact).where(CampaignContact.campaign_id == ready.campaign_id))
        assert row is not None
        row.status = "PENDING"
        session.commit()
    confirmed = client.post(f"/api/v1/campaigns/{ready.campaign_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "READY"


def test_dry_run_skips_gmail_and_marks_the_sheet(mail) -> None:
    ready = mail.ready()
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    log = logging.getLogger("app.services.email_service")
    handler = _Capture()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.disabled = False
    log._cache.clear()
    try:
        with SessionLocal() as session:
            start_campaign(session, ready.campaign_id)
            session.commit()
            result = dispatch_once(
                session,
                worker_id="worker-test",
                gmail=FakeGmailClient(),
                sheets=mail.fake,
                jitter_seconds=_NO_JITTER,
            )
            assert result.action == "dry_run"
            job = session.get(EmailJob, result.job_id)
            assert job is not None
            assert job.status == "SKIPPED"
            assert job.dry_run is True
            assert job.gmail_message_id is None
            history = session.scalar(
                select(func.count()).select_from(EmailHistory).where(EmailHistory.email_job_id == job.id)
            )
            assert history == 0
            campaign = session.get(Campaign, ready.campaign_id)
            assert campaign is not None
            assert campaign.status == "COMPLETED"
    finally:
        log.removeHandler(handler)

    text = "\n".join(captured)
    assert "Would send:" in text
    assert ready.emails[0] in text
    assert "Hello Ada" in text
    assert "Role Engineer" not in text
    grid = mail.fake.read_tab(ready.spreadsheet_id, "Sheet1")
    assert grid.rows[0] is not None
    assert grid.rows[0][4] == "NOT_SENT"
    assert grid.rows[0][9] == "dry_run"


def test_multi_row_dry_run_respects_the_delay(mail) -> None:
    ready = mail.ready(rows=2)
    with SessionLocal() as session:
        settings_row = session.get(AppSettings, 1)
        assert settings_row is not None
        settings_row.delay_between_emails_seconds = 60
        session.commit()
        start_campaign(session, ready.campaign_id)
        session.commit()
        moment = datetime.now(UTC)
        gmail = FakeGmailClient()
        first = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            now=moment,
            jitter_seconds=_NO_JITTER,
        )
        second = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            now=moment,
            jitter_seconds=_NO_JITTER,
        )
        assert first.action == "dry_run"
        assert second.action == "limited"
        third = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=gmail,
            sheets=mail.fake,
            now=moment + timedelta(seconds=61),
            jitter_seconds=_NO_JITTER,
        )
        assert third.action == "dry_run"
        assert len(gmail.sent) == 0
        campaign = session.get(Campaign, ready.campaign_id)
        assert campaign is not None
        assert campaign.status == "COMPLETED"


def test_pause_stops_the_next_claim(mail) -> None:
    ready = mail.ready()
    with SessionLocal() as session:
        start_campaign(session, ready.campaign_id)
        pause_campaign(session, ready.campaign_id)
        session.commit()
        result = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=FakeGmailClient(),
            sheets=mail.fake,
            jitter_seconds=_NO_JITTER,
        )
        assert result.action == "idle"
        job = session.scalar(select(EmailJob).where(EmailJob.campaign_id == ready.campaign_id))
        assert job is not None
        assert job.status == "QUEUED"


def test_hourly_cap_blocks_the_next_send(mail) -> None:
    ready = mail.ready(rows=2)
    with SessionLocal() as session:
        settings_row = session.get(AppSettings, 1)
        assert settings_row is not None
        settings_row.emails_per_hour = 1
        session.commit()
        start_campaign(session, ready.campaign_id)
        session.commit()
        moment = datetime.now(UTC)
        first = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=FakeGmailClient(),
            sheets=mail.fake,
            now=moment,
            jitter_seconds=_NO_JITTER,
        )
        second = dispatch_once(
            session,
            worker_id="worker-test",
            gmail=FakeGmailClient(),
            sheets=mail.fake,
            now=moment,
            jitter_seconds=_NO_JITTER,
        )
        assert first.action == "dry_run"
        assert second.action == "limited"
        waiting = session.scalar(
            select(func.count()).select_from(EmailJob).where(
                EmailJob.campaign_id == ready.campaign_id,
                EmailJob.status == "QUEUED",
            )
        )
        assert waiting == 1


def test_real_send_stores_the_gmail_id_before_the_sheet_write(mail, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)
    ready = mail.ready()
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
        job = session.get(EmailJob, result.job_id)
        assert job is not None
        assert job.status == "SENT"
        assert job.gmail_message_id == "test-message-1"
        assert job.sent_at is not None
        history = session.scalar(select(EmailHistory).where(EmailHistory.email_job_id == job.id))
        assert history is not None
        assert history.status == "SENT"
        assert history.subject == "Hello Ada"
    assert len(gmail.sent) == 1
    assert gmail.sent[0].to == ready.emails[0]
    assert gmail.sent[0].subject == "Hello Ada"
    assert gmail.sent[0].attachment_filename == "fullstack_resume.pdf"
    assert gmail.sent[0].attachment_bytes.startswith(b"%PDF")
    assert "Role Engineer" == gmail.sent[0].body
    grid = mail.fake.read_tab(ready.spreadsheet_id, "Sheet1")
    assert grid.rows[0] is not None
    assert grid.rows[0][4] == "SENT"


def test_dispatch_interval_is_ten_seconds() -> None:
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["dispatch-due-email"]
    assert schedule["schedule"] == 10.0
    assert schedule["options"]["queue"] == "email"
    assert celery_app.conf.worker_pool == "solo"
