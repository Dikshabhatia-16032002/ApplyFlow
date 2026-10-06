"""Build a ready campaign against an in-memory sheet for mail tests."""

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text

from app.db import SessionLocal
from app.integrations.sheets_client import STATUS_HEADERS, FakeSheetsClient
from app.models import AppSettings, Campaign, CampaignContact, Contact, EmailTemplate, Resume, SheetConnection
from app.seed import seed
from app.services import campaign_service

_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@dataclass
class ReadyRun:
    campaign_id: UUID
    spreadsheet_id: str
    emails: list[str]


@pytest.fixture
def mail(client, storage, monkeypatch):
    fake = FakeSheetsClient()
    monkeypatch.setattr(campaign_service, "get_sheets_client", lambda: fake)
    with SessionLocal() as session:
        seed(session)
        settings_row = session.get(AppSettings, 1)
        assert settings_row is not None
        original = (
            settings_row.emails_per_hour,
            settings_row.delay_between_emails_seconds,
            settings_row.max_daily_emails,
            settings_row.max_attempts,
            settings_row.gmail_reconnect_required,
        )
        settings_row.emails_per_hour = 1000
        settings_row.delay_between_emails_seconds = 0
        settings_row.max_daily_emails = 10000
        settings_row.max_attempts = 3
        settings_row.gmail_reconnect_required = False
        session.commit()

    world = _MailWorld(fake, storage)
    yield world

    with SessionLocal() as session:
        session.execute(
            text(
                """
                DELETE FROM email_attempts
                WHERE email_job_id IN (
                    SELECT email_jobs.id FROM email_jobs
                    JOIN campaigns ON campaigns.id = email_jobs.campaign_id
                    JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                    WHERE sheet_connection.spreadsheet_id LIKE 'test-mail-%'
                )
                """
            )
        )
        session.execute(
            text(
                """
                DELETE FROM email_history
                WHERE campaign_id IN (
                    SELECT campaigns.id FROM campaigns
                    JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                    WHERE sheet_connection.spreadsheet_id LIKE 'test-mail-%'
                )
                """
            )
        )
        session.execute(
            text(
                """
                DELETE FROM email_jobs
                WHERE campaign_id IN (
                    SELECT campaigns.id FROM campaigns
                    JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                    WHERE sheet_connection.spreadsheet_id LIKE 'test-mail-%'
                )
                """
            )
        )
        contact_ids = session.scalars(
            text(
                """
                SELECT campaign_contacts.contact_id FROM campaign_contacts
                JOIN campaigns ON campaigns.id = campaign_contacts.campaign_id
                JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                WHERE sheet_connection.spreadsheet_id LIKE 'test-mail-%'
                """
            )
        ).all()
        session.execute(
            text(
                """
                DELETE FROM campaign_contacts
                WHERE campaign_id IN (
                    SELECT campaigns.id FROM campaigns
                    JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                    WHERE sheet_connection.spreadsheet_id LIKE 'test-mail-%'
                )
                """
            )
        )
        session.execute(
            text(
                """
                DELETE FROM campaigns
                WHERE sheet_connection_id IN (
                    SELECT id FROM sheet_connection WHERE spreadsheet_id LIKE 'test-mail-%'
                )
                """
            )
        )
        if contact_ids:
            session.execute(delete(Contact).where(Contact.id.in_(contact_ids)))
        session.execute(text("DELETE FROM sheet_connection WHERE spreadsheet_id LIKE 'test-mail-%'"))
        session.execute(text("DELETE FROM resumes WHERE name LIKE 'Test Mail %'"))
        session.execute(text("DELETE FROM email_templates WHERE name LIKE 'Test Mail %'"))
        settings_row = session.get(AppSettings, 1)
        if settings_row is not None:
            (
                settings_row.emails_per_hour,
                settings_row.delay_between_emails_seconds,
                settings_row.max_daily_emails,
                settings_row.max_attempts,
                settings_row.gmail_reconnect_required,
            ) = original
        session.commit()


class _MailWorld:
    def __init__(self, fake: FakeSheetsClient, storage) -> None:
        self.fake = fake
        self.storage = storage

    def ready(
        self,
        *,
        rows: int = 1,
        email: str | None = None,
        status: str = "PENDING",
        campaign_status: str = "READY",
    ) -> ReadyRun:
        token = uuid4().hex[:8]
        spreadsheet_id = f"test-mail-{token}"
        headers = ["Name", "Email", "Role", "Company", *STATUS_HEADERS]
        emails: list[str] = []
        sheet_rows: list[list[str]] = []
        for index in range(rows):
            address = email if email is not None and rows == 1 else f"person-{index}-{token}@example.com"
            emails.append(address)
            sheet_rows.append(["Ada", address, "Engineer", "Acme", "", "", "", "", "", ""])
        self.fake.add_spreadsheet(spreadsheet_id, [("Sheet1", headers, sheet_rows)])

        key = f"{token}.pdf"
        (self.storage / key).write_bytes(_PDF)
        with SessionLocal() as session:
            resume = Resume(
                name=f"Test Mail Resume {token}",
                original_filename="fullstack_resume.pdf",
                storage_key=key,
                content_type="application/pdf",
                size_bytes=len(_PDF),
                sha256=hashlib.sha256(_PDF).hexdigest(),
                is_active=True,
            )
            template = EmailTemplate(
                name=f"Test Mail {token}",
                subject="Hello {{name}}",
                body="Role {{role}}",
                is_active=True,
            )
            session.add_all([resume, template])
            session.flush()
            connection = SheetConnection(
                spreadsheet_id=spreadsheet_id,
                spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                sheet_name="Sheet1",
                status_columns={name: headers.index(name) for name in STATUS_HEADERS},
            )
            session.add(connection)
            session.flush()
            campaign = Campaign(
                name=f"Test mail {token}",
                status=campaign_status,
                sheet_connection_id=connection.id,
            )
            session.add(campaign)
            session.flush()
            for index, address in enumerate(emails):
                contact = Contact(email=address, name="Ada", company="Acme")
                session.add(contact)
                session.flush()
                session.add(
                    CampaignContact(
                        campaign_id=campaign.id,
                        contact_id=contact.id,
                        sheet_row=index + 2,
                        name="Ada",
                        company="Acme",
                        role="Engineer",
                        resume_id=resume.id,
                        template_id=template.id,
                        status=status,
                        matched_keywords=[],
                        validation_errors=[],
                    )
                )
            campaign_id = campaign.id
            session.commit()
        return ReadyRun(campaign_id=campaign_id, spreadsheet_id=spreadsheet_id, emails=emails)
