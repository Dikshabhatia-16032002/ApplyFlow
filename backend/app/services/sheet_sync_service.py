import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import AppError, not_found
from app.config import get_settings
from app.integrations.sheets_client import SheetsClient, SheetsError, StatusWrite, get_sheets_client
from app.models import Campaign, CampaignContact, Contact, SheetConnection
from app.schemas.sheet import HeaderMapInput, SheetOut, SyncSummary
from app.services.match_resolution import MatchContext, load_match_context, match_role
from app.services.sheet_headers import (
    clip_cell,
    column_indexes,
    parse_spreadsheet_id,
    resolve_header_map,
    valid_email,
)

logger = logging.getLogger(__name__)


def get_sheet(session: Session) -> SheetOut:
    connection = _connection(session)
    if connection is None:
        raise not_found("Sheet")
    return _sheet_out(connection)


def save_sheet(session: Session, url: str, sheet_name: str | None) -> SheetOut:
    _refuse_if_busy(session)
    spreadsheet_id = parse_spreadsheet_id(url)
    if spreadsheet_id is None:
        raise AppError(422, "invalid_sheet_url", "Paste a Google Sheets link")
    name = sheet_name.strip() if sheet_name else None
    connection = _connection(session)
    if connection is None:
        connection = SheetConnection(spreadsheet_id=spreadsheet_id, spreadsheet_url=url.strip(), sheet_name=name)
        session.add(connection)
    else:
        if connection.spreadsheet_id != spreadsheet_id:
            connection.header_map = None
            connection.status_columns = None
        connection.spreadsheet_id = spreadsheet_id
        connection.spreadsheet_url = url.strip()
        connection.sheet_name = name
    session.flush()
    session.refresh(connection)
    return _sheet_out(connection)


def sync_sheet(session: Session, *, client: SheetsClient | None = None) -> SyncSummary:
    _refuse_if_busy(session)
    connection = _connection(session)
    if connection is None:
        raise not_found("Sheet")
    return _sync(session, connection, client or get_sheets_client(), campaign=None)


def save_mapping_and_sync(session: Session, campaign_id: UUID, mapping: HeaderMapInput) -> SyncSummary:
    _refuse_if_busy(session)
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise not_found("Campaign")
    if campaign.status != "DRAFT":
        raise AppError(409, "campaign_not_draft", "Header mapping applies to a draft run")
    connection = session.get(SheetConnection, campaign.sheet_connection_id)
    if connection is None:
        raise not_found("Sheet")
    header_map = mapping.as_map()
    if "email" not in header_map or "role" not in header_map:
        raise AppError(422, "header_mapping_required", "Map both the email and role columns")
    connection.header_map = header_map
    session.flush()
    return _sync(session, connection, get_sheets_client(), campaign=campaign)


def _sync(
    session: Session,
    connection: SheetConnection,
    client: SheetsClient,
    *,
    campaign: Campaign | None,
) -> SyncSummary:
    try:
        grid = client.read_tab(connection.spreadsheet_id, connection.sheet_name)
    except SheetsError as exc:
        raise AppError(422, exc.code, exc.detail) from exc

    data_rows = [(index, row) for index, row in enumerate(grid.rows) if not _blank(row)]
    if not data_rows:
        raise AppError(422, "empty_sheet", "The sheet has no data rows")
    max_rows = get_settings().max_sheet_rows
    if len(data_rows) > max_rows:
        raise AppError(422, "sheet_too_large", f"The sheet has more than {max_rows} data rows")

    mapping = resolve_header_map(grid.headers, _saved_map(connection.header_map))
    if "email" not in mapping or "role" not in mapping:
        draft = campaign or _empty_draft(session, connection)
        session.commit()
        raise AppError(
            422,
            "header_mapping_required",
            "Map the email and role columns before syncing",
            headers=list(grid.headers),
            campaign_id=str(draft.id),
        )

    indexes = column_indexes(grid.headers, mapping)
    try:
        status_indexes = client.ensure_status_columns(connection.spreadsheet_id, grid.tab_name)
    except SheetsError as exc:
        raise AppError(422, exc.code, exc.detail) from exc

    context = load_match_context(session)
    outcomes = [_classify(row, indexes, status_indexes, context) for _offset, row in data_rows]
    _mark_duplicates(outcomes)
    writes = [
        StatusWrite(sheet_row=offset + 2, values=outcome.sheet_values)
        for (offset, _row), outcome in zip(data_rows, outcomes, strict=True)
        if outcome.sheet_values is not None
    ]
    try:
        client.write_status_cells(connection.spreadsheet_id, grid.tab_name, writes)
    except SheetsError as exc:
        raise AppError(422, exc.code, exc.detail) from exc

    target = campaign if campaign is not None else _new_campaign(session, connection)
    if campaign is not None:
        _clear_contacts(session, campaign.id)
    paired = list(zip(data_rows, outcomes, strict=True))
    kept = [item for item in paired if item[1].valid or item[1].sent]
    skipped = [item for item in paired if not item[1].valid and not item[1].sent and not item[1].counts_as_duplicate]
    stored_emails: set[str] = set()
    for (offset, row), outcome in [*kept, *skipped]:
        if outcome.skip_database or outcome.counts_as_duplicate:
            continue
        contact_email = outcome.contact_email
        if contact_email is not None and contact_email in stored_emails:
            outcome.skip_database = True
            continue
        if contact_email is not None:
            stored_emails.add(contact_email)
        _store_row(session, target, sheet_row=offset + 2, row=row, indexes=indexes, outcome=outcome)

    connection.header_map = mapping
    connection.status_columns = status_indexes
    connection.last_synced_at = datetime.now(UTC)
    session.flush()
    logger.info("sheet sync finished", extra={"campaign_id": str(target.id), "status": "DRAFT"})
    return _summary(target.id, outcomes)


@dataclass
class _Outcome:
    status: str
    skip_reason: str | None
    validation_errors: list[str]
    sheet_values: dict[str, str] | None
    email: str | None
    contact_email: str | None
    counts_as_duplicate: bool = False
    skip_database: bool = False
    sent: bool = False
    valid: bool = False
    profile_id: UUID | None = None
    match_confidence: Decimal | None = None
    match_method: str | None = None
    matched_keywords: tuple[str, ...] = ()
    resume_id: UUID | None = None
    template_id: UUID | None = None
    profile_name: str = ""
    resume_name: str = ""
    template_name: str = ""


def _classify(
    row: list[str] | None,
    indexes: dict[str, int],
    status_indexes: dict[str, int],
    context: MatchContext,
) -> _Outcome:
    if row is None:
        return _Outcome(
            status="SKIPPED",
            skip_reason="malformed",
            validation_errors=["malformed"],
            sheet_values=_not_sent("malformed"),
            email=None,
            contact_email=None,
        )
    email = _valid_email(row, indexes)
    contact_email = email or _raw_email(row, indexes)
    if _cell(row, status_indexes.get("outreach_status")).strip().upper() == "SENT":
        return _Outcome(
            status="SENT",
            skip_reason=None,
            validation_errors=[],
            sheet_values=None,
            email=email,
            contact_email=contact_email,
            sent=True,
            valid=email is not None and _has_role(row, indexes),
        )
    errors = _validation_errors(row, indexes)
    if errors:
        return _Outcome(
            status="SKIPPED",
            skip_reason="invalid",
            validation_errors=errors,
            sheet_values=_not_sent(errors[0]),
            email=None,
            contact_email=contact_email,
        )
    resolved = match_role(context, _cell(row, indexes.get("role")), _optional(row, indexes, "job_description"))
    return _Outcome(
        status=resolved.status,
        skip_reason=resolved.reason,
        validation_errors=[],
        sheet_values=_not_sent(
            resolved.reason or "",
            profile=resolved.profile_name,
            resume=resolved.resume_name,
            template=resolved.template_name,
        ),
        email=email,
        contact_email=email,
        valid=True,
        profile_id=resolved.profile_id,
        match_confidence=resolved.confidence,
        match_method=resolved.method,
        matched_keywords=resolved.matched_keywords,
        resume_id=resolved.resume_id,
        template_id=resolved.template_id,
        profile_name=resolved.profile_name,
        resume_name=resolved.resume_name,
        template_name=resolved.template_name,
    )


def _mark_duplicates(outcomes: list[_Outcome]) -> None:
    seen: set[str] = set()
    for outcome in outcomes:
        if outcome.sent:
            if outcome.email and outcome.email in seen:
                outcome.skip_database = True
            elif outcome.email:
                seen.add(outcome.email)
            continue
        if not outcome.valid or outcome.email is None:
            continue
        if outcome.email in seen:
            outcome.counts_as_duplicate = True
            outcome.valid = False
            outcome.status = "SKIPPED"
            outcome.sheet_values = _not_sent("duplicate_in_sheet")
            continue
        seen.add(outcome.email)


def _store_row(
    session: Session,
    campaign: Campaign,
    *,
    sheet_row: int,
    row: list[str] | None,
    indexes: dict[str, int],
    outcome: _Outcome,
) -> None:
    contact = _upsert_contact(session, outcome.contact_email, row, indexes)
    session.add(
        CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            sheet_row=sheet_row,
            name=_optional(row, indexes, "name"),
            company=_optional(row, indexes, "company"),
            role=_optional(row, indexes, "role"),
            original_role=_optional(row, indexes, "role"),
            location=_optional(row, indexes, "location"),
            mobile=_optional(row, indexes, "mobile"),
            linkedin_url=_optional(row, indexes, "linkedin_url"),
            job_description=_optional(row, indexes, "job_description"),
            notes=_optional(row, indexes, "notes"),
            profile_id=outcome.profile_id,
            match_confidence=outcome.match_confidence,
            match_method=outcome.match_method,
            matched_keywords=list(outcome.matched_keywords),
            resume_id=outcome.resume_id,
            template_id=outcome.template_id,
            status=outcome.status,
            skip_reason=outcome.skip_reason,
            validation_errors=list(outcome.validation_errors),
        )
    )


def _upsert_contact(session: Session, email: str | None, row: list[str] | None, indexes: dict[str, int]) -> Contact:
    stored = email if email else f"missing-{uuid4()}@invalid.local"
    contact = session.scalar(select(Contact).where(Contact.email == stored))
    if contact is None:
        contact = Contact(email=stored)
        session.add(contact)
        session.flush()
    for attribute, field in (
        ("name", "name"),
        ("mobile", "mobile"),
        ("company", "company"),
        ("linkedin_url", "linkedin_url"),
    ):
        value = _optional(row, indexes, field)
        if value:
            setattr(contact, attribute, value)
    return contact


def _summary(campaign_id: UUID, outcomes: list[_Outcome]) -> SyncSummary:
    skipped_duplicate = sum(1 for outcome in outcomes if outcome.counts_as_duplicate)
    skipped_invalid = sum(
        1
        for outcome in outcomes
        if outcome.skip_reason in {"invalid", "malformed"} and not outcome.counts_as_duplicate
    )
    already_sent = sum(1 for outcome in outcomes if outcome.sent)
    needs_review = sum(1 for outcome in outcomes if outcome.valid and outcome.status == "NEEDS_REVIEW")
    pending = sum(1 for outcome in outcomes if outcome.status == "PENDING")
    return SyncSummary(
        campaign_id=campaign_id,
        rows_read=len(outcomes),
        valid=sum(1 for outcome in outcomes if outcome.valid),
        needs_review=needs_review,
        not_sent=skipped_invalid + skipped_duplicate + needs_review + pending,
        already_sent=already_sent,
        skipped_invalid=skipped_invalid,
        skipped_duplicate=skipped_duplicate,
    )


def _empty_draft(session: Session, connection: SheetConnection) -> Campaign:
    drafts = session.scalars(
        select(Campaign)
        .where(Campaign.sheet_connection_id == connection.id, Campaign.status == "DRAFT")
        .order_by(Campaign.created_at.desc())
    ).all()
    for draft in drafts:
        count = session.scalar(
            select(func.count()).select_from(CampaignContact).where(CampaignContact.campaign_id == draft.id)
        )
        if not count:
            return draft
    return _new_campaign(session, connection)


def _new_campaign(session: Session, connection: SheetConnection) -> Campaign:
    campaign = Campaign(
        name=f"Sheet run {datetime.now(UTC).date().isoformat()}",
        status="DRAFT",
        sheet_connection_id=connection.id,
    )
    session.add(campaign)
    session.flush()
    return campaign


def _clear_contacts(session: Session, campaign_id: UUID) -> None:
    rows = session.scalars(select(CampaignContact).where(CampaignContact.campaign_id == campaign_id)).all()
    for row in rows:
        session.delete(row)
    session.flush()


def _refuse_if_busy(session: Session) -> None:
    busy = session.scalar(select(Campaign.id).where(Campaign.status.in_(("RUNNING", "PAUSED"))).limit(1))
    if busy is not None:
        raise AppError(409, "sync_in_progress", "Sync is unavailable while a run is in progress")


def _connection(session: Session) -> SheetConnection | None:
    return session.scalar(select(SheetConnection).order_by(SheetConnection.created_at).limit(1))


def _sheet_out(connection: SheetConnection) -> SheetOut:
    return SheetOut(
        spreadsheet_id=connection.spreadsheet_id,
        spreadsheet_url=connection.spreadsheet_url,
        sheet_name=connection.sheet_name,
        header_map=_saved_map(connection.header_map),
        last_synced_at=connection.last_synced_at,
    )


def _saved_map(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): str(item) for key, item in value.items() if item}


def _validation_errors(row: list[str], indexes: dict[str, int]) -> list[str]:
    errors: list[str] = []
    if _valid_email(row, indexes) is None:
        errors.append("invalid_email")
    if not _has_role(row, indexes):
        errors.append("missing_role")
    return errors


def _has_role(row: list[str], indexes: dict[str, int]) -> bool:
    return bool(_cell(row, indexes.get("role")).strip())


def _not_sent(reason: str, *, profile: str = "", resume: str = "", template: str = "") -> dict[str, str]:
    return {
        "outreach_status": "NOT_SENT",
        "sent_at": "",
        "detected_profile": profile,
        "resume_name": resume,
        "template_name": template,
        "outreach_error": reason,
    }


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return clip_cell(str(row[index]))


def _valid_email(row: list[str], indexes: dict[str, int]) -> str | None:
    raw = _cell(row, indexes.get("email")).strip().lower()
    if not valid_email(raw):
        return None
    return raw


def _raw_email(row: list[str], indexes: dict[str, int]) -> str | None:
    raw = _cell(row, indexes.get("email")).strip().lower()
    return raw or None


def _optional(row: list[str] | None, indexes: dict[str, int], field: str) -> str | None:
    if row is None:
        return None
    value = _cell(row, indexes.get(field)).strip()
    return value or None


def _blank(row: list[str] | None) -> bool:
    if row is None:
        return False
    return all(not str(cell).strip() for cell in row)
