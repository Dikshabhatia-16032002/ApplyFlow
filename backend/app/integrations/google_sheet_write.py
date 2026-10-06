"""Write status cells to the connected Google Sheet."""

import json
import urllib.error
import urllib.parse
import urllib.request

from app.db import SessionLocal
from app.integrations.gmail_client import GmailError, bearer_token, refreshed_bearer_token
from app.integrations.sheets_client import STATUS_HEADERS, SheetsError, StatusWrite

_API = "https://sheets.googleapis.com/v4/spreadsheets"


def push_status_cells(spreadsheet_id: str, sheet_name: str | None, writes: list[StatusWrite]) -> None:
    if not writes:
        return
    token = _token(refresh=False)
    try:
        _push(token, spreadsheet_id, sheet_name, writes)
    except SheetsError as exc:
        if exc.code != "auth":
            raise
        token = _token(refresh=True)
        _push(token, spreadsheet_id, sheet_name, writes)


def _push(token: str, spreadsheet_id: str, sheet_name: str | None, writes: list[StatusWrite]) -> None:
    title = sheet_name or _first_sheet_title(token, spreadsheet_id)
    headers = _header_row(token, spreadsheet_id, title)
    missing = [header for header in STATUS_HEADERS if header not in _positions(headers)]
    if missing:
        headers = [*headers, *missing]
        _put_values(token, spreadsheet_id, _a1(title, 1, 1, len(headers)), [headers])
    positions = _positions(headers)
    data: list[dict[str, object]] = []
    for write in writes:
        for header, value in write.values.items():
            column = positions.get(header)
            if column is None:
                raise SheetsError("sheet_unavailable", f"The sheet is missing {header}")
            data.append({"range": _cell(title, column, write.sheet_row), "values": [[value]]})
    if data:
        _post(
            token,
            f"{_API}/{urllib.parse.quote(spreadsheet_id, safe='')}/values:batchUpdate",
            {"valueInputOption": "RAW", "data": data},
        )


def _token(*, refresh: bool) -> str:
    with SessionLocal() as session:
        try:
            token = refreshed_bearer_token(session) if refresh else bearer_token(session)
        except GmailError as exc:
            raise SheetsError("auth", "Gmail authorization failed") from exc
        session.commit()
        return token


def _first_sheet_title(token: str, spreadsheet_id: str) -> str:
    payload = _get(
        token,
        f"{_API}/{urllib.parse.quote(spreadsheet_id, safe='')}?fields=sheets.properties.title",
    )
    sheets = payload.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    properties = sheets[0].get("properties") if isinstance(sheets[0], dict) else None
    title = properties.get("title") if isinstance(properties, dict) else None
    if not isinstance(title, str) or not title:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    return title


def _header_row(token: str, spreadsheet_id: str, title: str) -> list[str]:
    quoted = urllib.parse.quote(f"{_quote_title(title)}!1:1", safe="")
    payload = _get(token, f"{_API}/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{quoted}")
    values = payload.get("values")
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        return []
    return [str(cell) for cell in values[0]]


def _put_values(token: str, spreadsheet_id: str, range_name: str, rows: list[list[str]]) -> None:
    quoted = urllib.parse.quote(range_name, safe="")
    url = (
        f"{_API}/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{quoted}"
        "?valueInputOption=RAW"
    )
    _request(token, url, {"range": range_name, "majorDimension": "ROWS", "values": rows}, method="PUT")


def _positions(headers: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        if header in STATUS_HEADERS and header not in found:
            found[header] = index
    return found


def _a1(title: str, row: int, start_column: int, end_column: int | None) -> str:
    start = _column_name(start_column)
    if end_column is None:
        return f"{_quote_title(title)}!{start}{row}:{row}"
    end = _column_name(end_column)
    return f"{_quote_title(title)}!{start}{row}:{end}{row}"


def _cell(title: str, column: int, row: int) -> str:
    return f"{_quote_title(title)}!{_column_name(column + 1)}{row}"


def _quote_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _column_name(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _get(token: str, url: str) -> dict[str, object]:
    return _request(token, url, None, method="GET")


def _post(token: str, url: str, body: dict[str, object]) -> dict[str, object]:
    return _request(token, url, body, method="POST")


def _request(token: str, url: str, body: dict[str, object] | None, *, method: str) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SheetsError("auth", "Gmail authorization failed") from exc
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account") from exc
    if not isinstance(payload, dict):
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    return payload
