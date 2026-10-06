import pytest
from sqlalchemy import delete, func, select, text

from app.db import SessionLocal
from app.integrations.sheets_client import FakeSheetsClient, sample_rows
from app.models import Campaign, CampaignContact, Contact, EmailJob, Profile, SheetConnection
from app.seed import seed
from app.services import campaign_contact_service, sheet_sync_service
from app.services.sheet_headers import auto_header_map


@pytest.fixture
def sheet_api(client, monkeypatch):
    fake = FakeSheetsClient()
    monkeypatch.setattr(sheet_sync_service, "get_sheets_client", lambda: fake)
    monkeypatch.setattr(campaign_contact_service, "get_sheets_client", lambda: fake)
    with SessionLocal() as session:
        seed(session)
        session.commit()
    yield client, fake
    with SessionLocal() as session:
        contact_ids = session.scalars(
            text(
                """
                SELECT campaign_contacts.contact_id
                FROM campaign_contacts
                JOIN campaigns ON campaigns.id = campaign_contacts.campaign_id
                JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                WHERE sheet_connection.spreadsheet_id LIKE 'test-%'
                """
            )
        ).all()
        session.execute(
            text(
                """
                DELETE FROM email_jobs
                WHERE campaign_id IN (
                    SELECT campaigns.id FROM campaigns
                    JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                    WHERE sheet_connection.spreadsheet_id LIKE 'test-%'
                )
                """
            )
        )
        session.execute(
            text(
                """
                DELETE FROM campaign_contacts
                WHERE campaign_id IN (
                    SELECT campaigns.id FROM campaigns
                    JOIN sheet_connection ON sheet_connection.id = campaigns.sheet_connection_id
                    WHERE sheet_connection.spreadsheet_id LIKE 'test-%'
                )
                """
            )
        )
        session.execute(
            text(
                """
                DELETE FROM campaigns
                WHERE sheet_connection_id IN (
                    SELECT id FROM sheet_connection WHERE spreadsheet_id LIKE 'test-%'
                )
                """
            )
        )
        if contact_ids:
            session.execute(delete(Contact).where(Contact.id.in_(contact_ids)))
        session.execute(text("DELETE FROM sheet_connection WHERE spreadsheet_id LIKE 'test-%'"))
        session.commit()


def test_aliases_match_normalized_headers() -> None:
    mapping = auto_header_map(["Full Name", "E-mail", "Job Title", "Favorite Color"])
    assert mapping["name"] == "Full Name"
    assert mapping["email"] == "E-mail"
    assert mapping["role"] == "Job Title"
    assert "favorite color" not in mapping.values()


def test_sync_classifies_rows_and_leaves_sent_cells(sheet_api) -> None:
    api, fake = sheet_api
    headers, rows = sample_rows()
    fake.add_spreadsheet("test-sample", [("People", headers, rows)])
    _save(api, "test-sample")

    first = api.post("/api/v1/sheet/sync")
    assert first.status_code == 200
    body = first.json()
    assert body["rows_read"] == 5
    assert body["valid"] == 2
    assert body["needs_review"] == 1
    assert body["not_sent"] == 4
    assert body["already_sent"] == 1
    assert body["skipped_invalid"] == 2
    assert body["skipped_duplicate"] == 1

    grid = fake.read_tab("test-sample", "People")
    assert grid.headers.count("outreach_error") == 1
    assert grid.headers.count("detected_profile") == 1
    sent = grid.rows[4]
    assert sent is not None
    assert sent[grid.headers.index("outreach_status")] == "SENT"
    assert sent[grid.headers.index("sent_at")] == "2026-03-01T00:00:00Z"
    assert sent[grid.headers.index("outreach_error")] == ""

    first_row = grid.rows[0]
    assert first_row is not None
    assert first_row[grid.headers.index("outreach_status")] == "NOT_SENT"
    assert first_row[grid.headers.index("outreach_error")] == "missing_resume"
    assert first_row[grid.headers.index("detected_profile")] == "Frontend Engineer"
    assert first_row[grid.headers.index("resume_name")] == ""
    duplicate = grid.rows[3]
    assert duplicate is not None
    assert duplicate[grid.headers.index("outreach_error")] == "duplicate_in_sheet"

    with SessionLocal() as session:
        campaign = session.get(Campaign, body["campaign_id"])
        assert campaign is not None
        assert campaign.status == "DRAFT"
        jobs = session.scalar(select(func.count()).select_from(EmailJob).where(EmailJob.campaign_id == campaign.id))
        assert jobs == 0
        stored = session.scalars(select(CampaignContact).where(CampaignContact.campaign_id == campaign.id)).all()
        statuses = sorted(row.status for row in stored)
        assert statuses.count("SENT") == 1
        assert statuses.count("NEEDS_REVIEW") == 1
        assert "QUEUED" not in statuses
        review = next(row for row in stored if row.status == "NEEDS_REVIEW")
        assert review.match_method == "keyword"
        assert review.skip_reason == "missing_resume"
        profile = session.get(Profile, review.profile_id)
        assert profile is not None
        assert profile.name == "Frontend Engineer"

    second = api.post("/api/v1/sheet/sync")
    assert second.status_code == 200
    assert fake.read_tab("test-sample", "People").headers.count("outreach_error") == 1


def test_explicit_mapping_then_syncs_the_draft(sheet_api) -> None:
    api, fake = sheet_api
    fake.add_spreadsheet(
        "test-unmap",
        [("People", ["Person", "Workbox", "Opening"], [["Ada Lovelace", "ada@sheet.test", "Engineer"]])],
    )
    _save(api, "test-unmap")
    blocked = api.post("/api/v1/sheet/sync")
    assert blocked.status_code == 422
    error = blocked.json()
    assert error["code"] == "header_mapping_required"
    assert error["headers"] == ["Person", "Workbox", "Opening"]

    synced = api.post(
        f"/api/v1/campaigns/{error['campaign_id']}/mapping",
        json={"email": "Workbox", "role": "Opening", "name": "Person"},
    )
    assert synced.status_code == 200
    assert synced.json()["campaign_id"] == error["campaign_id"]
    assert synced.json()["needs_review"] == 1
    assert synced.json()["rows_read"] == 1

    with SessionLocal() as session:
        contacts = session.scalar(select(func.count()).select_from(Contact).where(Contact.email == "ada@sheet.test"))
        assert contacts == 1


def test_invalid_row_does_not_block_a_later_valid_row(sheet_api) -> None:
    api, fake = sheet_api
    fake.add_spreadsheet(
        "test-order",
        [
            (
                "People",
                ["Email", "Role"],
                [
                    ["ada@sheet.test", ""],
                    ["ada@sheet.test", "Engineer"],
                ],
            )
        ],
    )
    _save(api, "test-order")
    response = api.post("/api/v1/sheet/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["skipped_invalid"] == 1
    assert body["skipped_duplicate"] == 0
    assert body["needs_review"] == 1
    grid = fake.read_tab("test-order", None)
    assert grid.rows[0] is not None
    assert grid.rows[0][grid.headers.index("outreach_error")] == "missing_role"
    assert grid.rows[1] is not None
    assert grid.rows[1][grid.headers.index("outreach_error")] == "needs_review"


def test_blank_sheet_value_does_not_erase_a_saved_name(sheet_api) -> None:
    api, fake = sheet_api
    with SessionLocal() as session:
        session.add(Contact(email="ada@sheet.test", name="Ada", company="Old"))
        session.commit()
    fake.add_spreadsheet(
        "test-update",
        [("People", ["Name", "Email", "Role", "Company"], [["", "ada@sheet.test", "Engineer", "New"]])],
    )
    _save(api, "test-update")
    assert api.post("/api/v1/sheet/sync").status_code == 200
    with SessionLocal() as session:
        contact = session.scalar(select(Contact).where(Contact.email == "ada@sheet.test"))
        assert contact is not None
        assert contact.name == "Ada"
        assert contact.company == "New"
        snapshot = session.scalar(select(CampaignContact).where(CampaignContact.contact_id == contact.id))
        assert snapshot is not None
        assert snapshot.name is None
        assert snapshot.company == "New"


def test_row_cap_empty_sheet_and_active_run(sheet_api, monkeypatch) -> None:
    api, fake = sheet_api
    monkeypatch.setattr(sheet_sync_service.get_settings(), "max_sheet_rows", 1)
    fake.add_spreadsheet(
        "test-limit",
        [("People", ["Email", "Role"], [["a@sheet.test", "Engineer"], ["b@sheet.test", "Engineer"]])],
    )
    _save(api, "test-limit")
    too_big = api.post("/api/v1/sheet/sync")
    assert too_big.status_code == 422
    assert too_big.json()["code"] == "sheet_too_large"

    fake.add_spreadsheet("test-empty", [("People", ["Email", "Role"], [])])
    _save(api, "test-empty")
    empty = api.post("/api/v1/sheet/sync")
    assert empty.status_code == 422
    assert empty.json()["code"] == "empty_sheet"

    fake.add_spreadsheet("test-busy", [("People", ["Email", "Role"], [["a@sheet.test", "Engineer"]])])
    _save(api, "test-busy")
    with SessionLocal() as session:
        connection = session.scalar(select(SheetConnection).where(SheetConnection.spreadsheet_id == "test-busy"))
        assert connection is not None
        session.add(Campaign(name="Busy", status="RUNNING", sheet_connection_id=connection.id))
        session.commit()
    busy = api.post("/api/v1/sheet/sync")
    assert busy.status_code == 409
    assert busy.json()["code"] == "sync_in_progress"


def test_rejects_a_non_sheet_link(sheet_api) -> None:
    api, _fake = sheet_api
    response = api.put("/api/v1/sheet", json={"url": "https://example.com/not-a-sheet"})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_sheet_url"


def test_sync_examples_and_manual_profile_change(sheet_api, storage) -> None:
    api, fake = sheet_api
    with SessionLocal() as session:
        saved = [(profile.id, profile.resume_id, profile.email_template_id) for profile in session.scalars(select(Profile))]
        for profile in session.scalars(select(Profile)):
            profile.resume_id = None
            profile.email_template_id = None
        session.commit()
        frontend = session.scalar(select(Profile).where(Profile.name == "Frontend Engineer"))
        backend = session.scalar(select(Profile).where(Profile.name == "Backend Engineer"))
        assert frontend is not None and backend is not None
        frontend_id = str(frontend.id)
        backend_id = str(backend.id)

    try:
        _run_match_examples(api, fake, frontend_id, backend_id)
    finally:
        with SessionLocal() as session:
            for profile_id, resume_id, template_id in saved:
                profile = session.get(Profile, profile_id)
                if profile is None:
                    continue
                profile.resume_id = resume_id
                profile.email_template_id = template_id
            session.commit()


def _run_match_examples(api, fake, frontend_id: str, backend_id: str) -> None:
    _resume(api, "Test Frontend Resume", frontend_id)
    _resume(api, "Test Backend Resume", backend_id)
    resume_override = _resume(api, "Test Override Resume", None)
    _template(api, "Test Frontend Note", frontend_id)
    _template(api, "Test Backend Note", backend_id)

    fake.add_spreadsheet(
        "test-match",
        [
            (
                "People",
                ["Email", "Role", "Job Description"],
                [
                    ["genai@match.test", "GenAI Engineer", "large language models"],
                    ["ml@match.test", "Machine Learning Engineer", ""],
                    ["react@match.test", "React Developer", ""],
                    ["plain@match.test", "Engineer", ""],
                ],
            )
        ],
    )
    _save(api, "test-match")
    synced = api.post("/api/v1/sheet/sync")
    assert synced.status_code == 200
    body = synced.json()
    assert body["needs_review"] == 3
    assert body["valid"] == 4
    campaign_id = body["campaign_id"]

    contacts = api.get(f"/api/v1/campaigns/{campaign_id}/contacts?limit=20").json()["items"]
    by_email = {row["email"]: row for row in contacts}
    assert by_email["genai@match.test"]["profile_name"] == "Applied AI Engineer"
    assert by_email["genai@match.test"]["status"] == "NEEDS_REVIEW"
    assert by_email["ml@match.test"]["profile_name"] == "AI/ML Engineer"
    assert by_email["react@match.test"]["profile_name"] == "Frontend Engineer"
    assert by_email["react@match.test"]["resume_name"] == "Test Frontend Resume"
    assert by_email["react@match.test"]["template_name"] == "Test Frontend Note"
    assert by_email["react@match.test"]["status"] == "PENDING"
    assert by_email["plain@match.test"]["profile_name"] is None
    assert by_email["plain@match.test"]["skip_reason"] == "needs_review"

    grid = fake.read_tab("test-match", None)
    react_row = grid.rows[2]
    assert react_row is not None
    assert react_row[grid.headers.index("detected_profile")] == "Frontend Engineer"
    assert react_row[grid.headers.index("resume_name")] == "Test Frontend Resume"
    assert react_row[grid.headers.index("template_name")] == "Test Frontend Note"
    assert react_row[grid.headers.index("outreach_error")] == ""

    overridden = api.patch(
        f"/api/v1/campaigns/{campaign_id}/contacts/{by_email['react@match.test']['id']}",
        json={"resume_id": resume_override},
    )
    assert overridden.status_code == 200
    assert overridden.json()["resume_name"] == "Test Override Resume"
    assert overridden.json()["resume_overridden"] is True
    assert overridden.json()["template_name"] == "Test Frontend Note"

    moved = api.patch(
        f"/api/v1/campaigns/{campaign_id}/contacts/{by_email['react@match.test']['id']}",
        json={"profile_id": backend_id},
    )
    assert moved.status_code == 200
    moved_body = moved.json()
    assert moved_body["profile_name"] == "Backend Engineer"
    assert moved_body["match_method"] == "manual"
    assert moved_body["match_confidence"] == "1.000"
    assert moved_body["resume_name"] == "Test Override Resume"
    assert moved_body["template_name"] == "Test Backend Note"
    assert moved_body["status"] == "PENDING"

    assigned = api.patch(
        f"/api/v1/campaigns/{campaign_id}/contacts/{by_email['plain@match.test']['id']}",
        json={"profile_id": frontend_id},
    )
    assert assigned.status_code == 200
    assert assigned.json()["profile_name"] == "Frontend Engineer"
    assert assigned.json()["resume_name"] == "Test Frontend Resume"
    assert assigned.json()["status"] == "PENDING"
    plain = fake.read_tab("test-match", None).rows[3]
    assert plain is not None
    assert plain[grid.headers.index("detected_profile")] == "Frontend Engineer"
    assert plain[grid.headers.index("outreach_error")] == ""


def _resume(api, name: str, profile_id: str | None) -> str:
    data = {"name": name}
    if profile_id:
        data["profile_ids"] = profile_id
    response = api.post(
        "/api/v1/resumes",
        files={"file": (f"{name}.pdf", b"%PDF-1.4\nmatch", "application/pdf")},
        data=data,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _template(api, name: str, profile_id: str) -> str:
    response = api.post(
        "/api/v1/templates",
        json={
            "name": name,
            "subject": "Role",
            "body": "Hello",
            "profile_ids": [profile_id],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _save(api, spreadsheet_id: str, sheet_name: str | None = None) -> None:
    payload: dict[str, str] = {"url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"}
    if sheet_name:
        payload["sheet_name"] = sheet_name
    response = api.put("/api/v1/sheet", json=payload)
    assert response.status_code == 200
