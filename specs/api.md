# HTTP API

Base path: `/api/v1`. JSON request and response bodies.

Errors:

```json
{ "detail": "human readable message", "code": "stable_code" }
```

Request-body validation uses FastAPI’s 422 shape.

List endpoints use `limit` and `offset`. Default limit 50, maximum 200.

## Health and Google

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Database and Redis reachability, `dry_run`, Gmail connected, sheet connected, `gmail_reconnect_required` |
| GET | `/auth/google/start` | Authorization URL for `gmail.send` and `spreadsheets` |
| GET | `/auth/google/callback` | Exchange the code, store encrypted tokens, redirect to the UI |
| GET | `/auth/google/status` | Connected email and scopes. No tokens. |
| POST | `/auth/google/disconnect` | Delete stored tokens and set `revoked_at` |

## Sheet

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/sheet` | URL, tab, spreadsheet id, last sync, header map |
| PUT | `/sheet` | Save or replace the one sheet URL and optional tab name |
| POST | `/sheet/sync` | Read rows, validate, match, write marks for rows that are not already `SENT`, open a `DRAFT` run |

`POST /sheet/sync` returns:

```json
{
  "campaign_id": "uuid",
  "rows_read": 0,
  "valid": 0,
  "needs_review": 0,
  "not_sent": 0,
  "already_sent": 0,
  "skipped_invalid": 0,
  "skipped_duplicate": 0
}
```

If email or role cannot be mapped, sync returns 422 with `code=header_mapping_required` and the detected headers. No contacts are created.

Sync returns 409 while a run is `RUNNING` or `PAUSED`.

## Profiles

| Method | Path | Purpose |
| --- | --- | --- |
| GET, POST | `/profiles` | List, create |
| GET, PATCH, DELETE | `/profiles/{id}` | Get, update, deactivate |
| PUT | `/profiles/{id}/keywords` | Replace the keyword list |

`DELETE` deactivates. It does not remove the row. Creating or replacing a keyword that another active profile already owns returns 409.

## Resumes

| Method | Path | Purpose |
| --- | --- | --- |
| GET, POST | `/resumes` | List; multipart PDF upload |
| GET | `/resumes/{id}` | Metadata |
| GET | `/resumes/{id}/file` | Download or inline preview |
| PATCH | `/resumes/{id}` | Rename, active, default, and the profiles that should point at it |
| POST | `/resumes/{id}/replace` | Replace PDF bytes; keep the id |

`POST` rejects a file that is over `MAX_RESUME_BYTES` (default 5 MB) or does not start with `%PDF`.

## Templates

| Method | Path | Purpose |
| --- | --- | --- |
| GET, POST | `/templates` | List, create |
| GET, PATCH, DELETE | `/templates/{id}` | Get, update, deactivate |
| POST | `/templates/{id}/duplicate` | Copy name, subject, and body. Profiles are not copied. |
| POST | `/templates/preview` | Render subject and body from sample or real fields. Does not send. |

The preview response includes the rendered subject, rendered body, empty variables, and unknown tokens.

## Campaigns

A campaign is one run against the connected sheet.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/campaigns` | List runs |
| GET | `/campaigns/{id}` | Detail plus counts: sent, failed, pending, skipped, needs review, sheet writes pending |
| POST | `/campaigns/{id}/mapping` | Save the header map, then sync that draft again |
| GET | `/campaigns/{id}/contacts` | Preview page |
| PATCH | `/campaigns/{id}/contacts/{contact_row_id}` | Edit profile, resume, template, name, company, role, `allow_resend` |
| POST | `/campaigns/{id}/contacts/{contact_row_id}/exclude` | Mark skipped and write `NOT_SENT` |
| POST | `/campaigns/{id}/contacts/{contact_row_id}/preview` | Rendered message for that row |
| POST | `/campaigns/{id}/confirm` | `DRAFT → READY` |
| POST | `/campaigns/{id}/start` | `READY → RUNNING` and enqueue |
| POST | `/campaigns/{id}/pause` | `RUNNING → PAUSED` |
| POST | `/campaigns/{id}/resume` | `PAUSED → RUNNING` |
| POST | `/campaigns/{id}/cancel` | Cancel queued jobs |
| POST | `/campaigns/{id}/rewrite-sheet` | Retry cells with `sheet_write_pending` |

Confirm returns 409 when any included row is `NEEDS_REVIEW` or is missing a resume or template.

Contact query parameters: `status`, `profile_id`, `resume_id`, `template_id`, `company`, `q` (name, email, company).

The shared sheet is the result log. There is no CSV or XLSX download in the MVP.

## Contacts, dashboard, settings

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/contacts` | Search and filters |
| GET | `/contacts/{id}` | Identity plus history timeline |
| GET | `/dashboard` | Totals and per-run counts |
| GET, PATCH | `/settings` | Rate limits, match threshold, max attempts |

Contact filters: `campaign_id`, `company`, `role`, `profile_id`, `status`, `resume_id`, `template_id`, `sent_from`, `sent_to`, and `q` over name, email, and company.

`PATCH /settings` accepts:

```json
{
  "emails_per_hour": 30,
  "delay_between_emails_seconds": 60,
  "max_daily_emails": 400,
  "match_confidence_threshold": 0.8,
  "max_attempts": 3
}
```

`DRY_RUN` is read from the environment and is not writable through this endpoint.
