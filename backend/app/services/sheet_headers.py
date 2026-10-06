import re

from app.utils.text import normalize_text

CONTACT_FIELDS = (
    "name",
    "email",
    "mobile",
    "company",
    "role",
    "job_description",
    "location",
    "linkedin_url",
    "notes",
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "full_name", "fullname", "contact_name", "recruiter_name"),
    "email": ("email", "e_mail", "email_address", "mail"),
    "mobile": ("mobile", "phone", "phone_number", "contact_number"),
    "company": ("company", "company_name", "organization", "organisation"),
    "role": ("role", "profile", "title", "job_title", "position", "job_role"),
    "job_description": ("job_description", "jd", "description"),
    "location": ("location", "city", "job_location"),
    "linkedin_url": ("linkedin_url", "linkedin", "linkedin_profile"),
    "notes": ("notes", "note", "comments"),
}

_ALIAS_TO_FIELD = {normalize_text(alias): field for field, aliases in _ALIASES.items() for alias in aliases}

_SHEET_ID = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CELL_LIMIT = 10_000


def parse_spreadsheet_id(url: str) -> str | None:
    match = _SHEET_ID.search(url.strip())
    if match is None:
        return None
    return match.group(1)


def valid_email(value: str) -> bool:
    return _EMAIL.fullmatch(value.strip().lower()) is not None


def clip_cell(value: str) -> str:
    return value[:CELL_LIMIT]


def auto_header_map(headers: list[str]) -> dict[str, str]:
    """Map contact fields to the original header text. First alias wins."""
    mapping: dict[str, str] = {}
    for header in headers:
        field = _ALIAS_TO_FIELD.get(normalize_text(header))
        if field is not None and field not in mapping:
            mapping[field] = header
    return mapping


def resolve_header_map(headers: list[str], saved: dict[str, str] | None) -> dict[str, str]:
    resolved = auto_header_map(headers)
    if not saved:
        return resolved
    available = {header: header for header in headers}
    for field, header in saved.items():
        if field not in CONTACT_FIELDS:
            continue
        if header in available:
            resolved[field] = header
        elif field in resolved and field in saved:
            resolved.pop(field, None)
    return resolved


def column_indexes(headers: list[str], mapping: dict[str, str]) -> dict[str, int]:
    positions = {header: index for index, header in enumerate(headers)}
    return {field: positions[header] for field, header in mapping.items() if header in positions}
