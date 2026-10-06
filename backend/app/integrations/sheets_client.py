from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.utils.text import normalize_text

STATUS_HEADERS = (
    "outreach_status",
    "sent_at",
    "detected_profile",
    "resume_name",
    "template_name",
    "outreach_error",
)

SAMPLE_SPREADSHEET_ID = "demo-sheet"
SAMPLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/demo-sheet/edit"


class SheetsError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass
class SheetGrid:
    tab_name: str
    headers: list[str]
    rows: list[list[str] | None]


@dataclass(frozen=True)
class StatusWrite:
    sheet_row: int
    values: dict[str, str]


@dataclass
class _Tab:
    headers: list[str]
    rows: list[list[str] | None]


class SheetsClient(Protocol):
    def read_tab(self, spreadsheet_id: str, sheet_name: str | None) -> SheetGrid: ...

    def ensure_status_columns(self, spreadsheet_id: str, sheet_name: str | None) -> dict[str, int]: ...

    def write_status_cells(self, spreadsheet_id: str, sheet_name: str | None, writes: list[StatusWrite]) -> None: ...


def sample_rows() -> tuple[list[str], list[list[str]]]:
    headers = ["Name", "Email", "Role", "Company", "outreach_status", "sent_at"]
    rows = [
        ["Rahul Sharma", "rahul@example.com", "Frontend Engineer", "Northwind", "", ""],
        ["Broken", "not-an-email", "Backend Engineer", "Acme", "", ""],
        ["No Role", "norole@example.com", "", "Initech", "", ""],
        ["Rahul Again", "rahul@example.com", "Frontend Engineer", "Northwind", "", ""],
        ["Sent Person", "sent@example.com", "Data Scientist", "Globex", "SENT", "2026-03-01T00:00:00Z"],
    ]
    return headers, rows


class FakeSheetsClient:
    """In-memory sheet. Phase 6 replaces this with the Google Sheets API."""

    def __init__(self) -> None:
        self._books: dict[str, dict[str, _Tab]] = {}

    def add_spreadsheet(
        self,
        spreadsheet_id: str,
        tabs: list[tuple[str, list[str], list[list[str] | None]]],
    ) -> None:
        self._books[spreadsheet_id] = {
            name: _Tab(headers=list(headers), rows=[None if row is None else list(row) for row in rows])
            for name, headers, rows in tabs
        }

    def load_sample(self) -> None:
        headers, rows = sample_rows()
        self.add_spreadsheet(SAMPLE_SPREADSHEET_ID, [("Sheet1", headers, rows)])

    def read_tab(self, spreadsheet_id: str, sheet_name: str | None) -> SheetGrid:
        tab_name, tab = self._tab(spreadsheet_id, sheet_name)
        return SheetGrid(tab_name=tab_name, headers=list(tab.headers), rows=[_copy_row(row) for row in tab.rows])

    def ensure_status_columns(self, spreadsheet_id: str, sheet_name: str | None) -> dict[str, int]:
        _tab_name, tab = self._tab(spreadsheet_id, sheet_name)
        indexes = _status_indexes(tab.headers)
        missing = [header for header in STATUS_HEADERS if header not in indexes]
        for header in missing:
            tab.headers.append(header)
            indexes[header] = len(tab.headers) - 1
        width = len(tab.headers)
        for index, row in enumerate(tab.rows):
            if row is None:
                continue
            if len(row) < width:
                tab.rows[index] = [*row, *([""] * (width - len(row)))]
        return indexes

    def write_status_cells(self, spreadsheet_id: str, sheet_name: str | None, writes: list[StatusWrite]) -> None:
        _tab_name, tab = self._tab(spreadsheet_id, sheet_name)
        indexes = _status_indexes(tab.headers)
        for write in writes:
            row_index = write.sheet_row - 2
            if row_index < 0 or row_index >= len(tab.rows):
                raise SheetsError("sheet_unavailable", "The sheet row is no longer available")
            row = tab.rows[row_index]
            if row is None:
                row = [""] * len(tab.headers)
                tab.rows[row_index] = row
            for header, value in write.values.items():
                column = indexes.get(header)
                if column is None:
                    raise SheetsError("sheet_unavailable", f"The sheet is missing {header}")
                while len(row) <= column:
                    row.append("")
                row[column] = value

    def _tab(self, spreadsheet_id: str, sheet_name: str | None) -> tuple[str, _Tab]:
        book = self._books.get(spreadsheet_id)
        if book is None or not book:
            raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
        if sheet_name:
            tab = book.get(sheet_name)
            if tab is None:
                raise SheetsError("sheet_tab_missing", f"The sheet has no tab named {sheet_name}")
            return sheet_name, tab
        name = next(iter(book))
        return name, book[name]


def _copy_row(row: list[str] | None) -> list[str] | None:
    if row is None:
        return None
    return list(row)


def _status_indexes(headers: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalize_text(header).replace(" ", "_")
        for name in STATUS_HEADERS:
            if key == name and name not in found:
                found[name] = index
    return found


class ReadingSheetsClient:
    """Serves the in-memory sample, and loads any other link-shared spreadsheet on read."""

    def __init__(
        self,
        inner: FakeSheetsClient,
        fetch: Callable[[str], tuple[list[str], list[list[str]]]] | None = None,
    ) -> None:
        self._inner = inner
        self._fetch = fetch

    def read_tab(self, spreadsheet_id: str, sheet_name: str | None) -> SheetGrid:
        if spreadsheet_id != SAMPLE_SPREADSHEET_ID:
            self._refresh(spreadsheet_id)
        return self._inner.read_tab(spreadsheet_id, sheet_name)

    def _refresh(self, spreadsheet_id: str) -> None:
        try:
            headers, rows = self._load(spreadsheet_id)
        except SheetsError:
            if not self._cached(spreadsheet_id):
                raise
            return
        self._inner.add_spreadsheet(spreadsheet_id, [("Sheet1", headers, rows)])

    def _cached(self, spreadsheet_id: str) -> bool:
        try:
            self._inner.read_tab(spreadsheet_id, None)
        except SheetsError:
            return False
        return True

    def ensure_status_columns(self, spreadsheet_id: str, sheet_name: str | None) -> dict[str, int]:
        return self._inner.ensure_status_columns(spreadsheet_id, sheet_name)

    def write_status_cells(self, spreadsheet_id: str, sheet_name: str | None, writes: list[StatusWrite]) -> None:
        if spreadsheet_id != SAMPLE_SPREADSHEET_ID:
            from app.integrations.google_sheet_write import push_status_cells

            push_status_cells(spreadsheet_id, sheet_name, writes)
        try:
            self._inner.write_status_cells(spreadsheet_id, sheet_name, writes)
        except SheetsError:
            if spreadsheet_id == SAMPLE_SPREADSHEET_ID:
                raise

    def _load(self, spreadsheet_id: str) -> tuple[list[str], list[list[str]]]:
        fetch = self._fetch
        if fetch is None:
            from app.integrations.public_sheet import fetch_public_sheet

            fetch = fetch_public_sheet
        return fetch(spreadsheet_id)


_MEMORY = FakeSheetsClient()
_MEMORY.load_sample()
_CLIENT = ReadingSheetsClient(_MEMORY)


def get_sheets_client() -> SheetsClient:
    return _CLIENT


__all__ = [
    "SAMPLE_SHEET_URL",
    "SAMPLE_SPREADSHEET_ID",
    "STATUS_HEADERS",
    "FakeSheetsClient",
    "ReadingSheetsClient",
    "SheetGrid",
    "SheetsClient",
    "SheetsError",
    "StatusWrite",
    "get_sheets_client",
    "sample_rows",
]
