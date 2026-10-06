"""Read the first tab of a link-shared Google Sheet."""

import json
import re
import urllib.error
import urllib.request

from app.integrations.sheets_client import SheetsError
from app.services.sheet_headers import auto_header_map

_GVIZ = "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:json&gid=0"
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def fetch_public_sheet(spreadsheet_id: str) -> tuple[list[str], list[list[str]]]:
    if _ID.fullmatch(spreadsheet_id) is None:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    request = urllib.request.Request(_GVIZ.format(spreadsheet_id=spreadsheet_id), headers={"User-Agent": "outreach"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account") from exc
    return parse_gviz(body)


def parse_gviz(body: str) -> tuple[list[str], list[list[str]]]:
    payload = _payload(body)
    if payload.get("status") != "ok":
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    table = payload.get("table")
    if not isinstance(table, dict):
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    labels = [str(column.get("label") or "").strip() for column in table.get("cols") or []]
    width = len(labels)
    rows: list[list[str]] = []
    for row in table.get("rows") or []:
        cells = [_cell(cell) for cell in (row.get("c") or [])]
        if width and len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        rows.append(cells)
    if any(labels):
        return labels, rows
    if not rows:
        return [], []
    first = [cell.strip() for cell in rows[0]]
    if auto_header_map(first):
        return first, rows[1:]
    count = max(len(row) for row in rows)
    return [f"Column {index + 1}" for index in range(count)], rows


def _payload(body: str) -> dict:
    marker = "setResponse("
    start = body.find(marker)
    if start < 0:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    blob = body[start + len(marker) :]
    end = blob.rfind(");")
    if end >= 0:
        blob = blob[:end]
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account") from exc
    if not isinstance(payload, dict):
        raise SheetsError("sheet_unavailable", "The spreadsheet is not available to this account")
    return payload


def _cell(cell: object) -> str:
    if not isinstance(cell, dict):
        return ""
    value = cell.get("f")
    if value is None:
        value = cell.get("v")
    if value is None:
        return ""
    return str(value).strip()
