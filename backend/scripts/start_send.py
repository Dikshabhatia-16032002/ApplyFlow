"""Sync the sheet, confirm the draft, and start sending.

The API must already be running on port 8000, and the worker must already be running.

    uv run python scripts/start_send.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000/api/v1"


def main() -> None:
    summary = _post("/sheet/sync")
    campaign_id = summary["campaign_id"]
    waiting = summary["not_sent"] - summary["needs_review"] - summary["skipped_invalid"] - summary["skipped_duplicate"]
    print(
        f"Synced {summary['rows_read']} rows. "
        f"{summary['already_sent']} already sent. "
        f"{waiting} waiting. "
        f"{summary['needs_review']} need review."
    )
    if summary["needs_review"]:
        raise SystemExit("Resolve the review rows on the Sheet page, then run this script again.")
    if waiting == 0:
        raise SystemExit("Nothing left to send.")
    confirmed = _post(f"/campaigns/{campaign_id}/confirm")
    print(f"Confirmed {confirmed['name']}.")
    started = _post(f"/campaigns/{campaign_id}/start")
    print(f"Started {started['name']}. The first email goes out within about 10 seconds.")


def _post(path: str) -> dict[str, object]:
    request = urllib.request.Request(f"{API}{path}", method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        try:
            message = json.loads(detail).get("detail") or detail
        except json.JSONDecodeError:
            message = detail or exc.reason
        raise SystemExit(message) from exc
    except urllib.error.URLError as exc:
        raise SystemExit("The API is not running. Start it, then run this script again.") from exc
    if not isinstance(body, dict):
        raise SystemExit("The API returned an unexpected response.")
    return body


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
