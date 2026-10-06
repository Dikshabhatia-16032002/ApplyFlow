# Data model

PostgreSQL. Primary keys are UUIDs. Timestamps are `timestamptz`. Schema changes go through Alembic only.

Emails are stored lowercased and trimmed. That normalized address is the unique key on `contacts`.

## Relationships

```text
users
  └── gmail_credentials (one connected account; Gmail send + this spreadsheet)

sheet_connection          (the one shared sheet)
  └── campaigns           (one review-and-send run against that sheet)
        └── campaign_contacts ──► contacts
              │
              └── email_jobs ──► email_attempts
                               └── email_history

profiles ──► resumes          (profiles.resume_id, nullable)
profiles ──► email_templates  (profiles.email_template_id, nullable)
profiles ──► profile_keywords

app_settings   (single row)
```

`contacts` is the person and survives across runs.

`campaign_contacts` is one sheet row in one run. Edits in the preview change this snapshot. They are not written back into the contact columns on the sheet.

`email_jobs` is the unit of sending. One job per campaign contact. That unique constraint makes queue creation idempotent.

`email_history` is the audit trail. The sheet cell `outreach_status` decides whether a row may be sent again. History is what the preview uses to warn on a resend.

`email_attempts` is the per-try log, including failures before the final status.

## users

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| email | text | Google account email once connected; nullable before that |
| display_name | text | Optional label in the UI |
| created_at, updated_at | timestamptz | |

The seed creates one user. Domain rows are not given a `user_id` in the MVP, so the schema does not pretend to be multi-tenant. A later phase can add those foreign keys.

## gmail_credentials

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| user_id | uuid fk users | unique |
| google_email | text | |
| refresh_token_encrypted | text | Fernet ciphertext |
| access_token_encrypted | text | nullable, short-lived |
| token_expiry | timestamptz | nullable |
| scopes | text | `gmail.send` and `spreadsheets` |
| connected_at | timestamptz | |
| revoked_at | timestamptz | nullable |

Scopes: `https://www.googleapis.com/auth/gmail.send` and `https://www.googleapis.com/auth/spreadsheets`. The spreadsheet scope is used only for the spreadsheet id on `sheet_connection`. Editor access on that sheet is required.

## sheet_connection

One row. Replacing the URL updates this row.

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| spreadsheet_id | text | parsed from the shared URL |
| spreadsheet_url | text | the link the operator pasted |
| sheet_name | text | tab name; default is the first tab |
| header_map | jsonb | field → column header, once mapping is confirmed |
| status_columns | jsonb | header name → column index for the six app-owned columns |
| last_synced_at | timestamptz | |
| created_at, updated_at | timestamptz | |

## profiles

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| name | text unique | e.g. `Frontend Engineer` |
| resume_id | uuid fk resumes null | resume used when this profile matches |
| email_template_id | uuid fk email_templates null | template used when this profile matches |
| is_active | bool | inactive profiles are not candidates |
| priority | int | higher wins a tie that would otherwise be a review; default 0 |
| created_at, updated_at | timestamptz | |

The profile name is also stored as a normalized keyword, so the title “Software Engineer” matches the profile of the same name.

Deleting a resume or template sets these foreign keys to null. Deactivation is the normal operator action.

## profile_keywords

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| profile_id | uuid fk | on delete cascade |
| keyword | text | normalized: lowercased, punctuation stripped, whitespace collapsed |
| unique (profile_id, keyword) | | |

The same keyword must not belong to two active profiles. The service rejects that save.

## resumes

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| name | text | operator-facing name |
| original_filename | text | |
| storage_key | text | relative key under the resume storage root; uuid filename |
| content_type | text | `application/pdf` |
| size_bytes | int | |
| sha256 | text | |
| is_active | bool | |
| is_default | bool | at most one row true; partial unique index |
| created_at, updated_at | timestamptz | |

Assigning a resume to profiles sets `profiles.resume_id` on each selected profile. A resume page lists the profiles that point at it. There is no second assignment table.

Resolution order:

1. `profiles.resume_id` when that resume is active.
2. Otherwise the active resume with `is_default = true`.
3. Otherwise the contact stays `NEEDS_REVIEW` with reason `missing_resume`.

## email_templates

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| name | text unique | |
| subject | text | max 200 characters |
| body | text | max 20,000 characters |
| is_active | bool | |
| is_default | bool | at most one true |
| created_at, updated_at | timestamptz | |

Resolution order matches resumes: the profile’s template, else the default active template, else `NEEDS_REVIEW` / `missing_template`.

Variables:

```text
{{name}} {{company}} {{role}} {{location}} {{mobile}} {{linkedin_url}}
```

`{{role}}` is the role on the campaign contact. It is the sheet value unless the operator edits it in the preview. It is not replaced with the profile name.

Unknown `{{tokens}}` are left unchanged and the preview shows a warning. Empty values become an empty string and the preview lists them.

## campaigns

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| name | text | default: `Sheet run` + date |
| status | text | check constraint; see lifecycle in architecture.md |
| sheet_connection_id | uuid fk | the single connected sheet |
| created_at | timestamptz | |
| confirmed_at | timestamptz | null until READY |
| started_at | timestamptz | |
| completed_at | timestamptz | |
| cancelled_at | timestamptz | |

Counts are aggregated from `campaign_contacts`. They are not stored.

## contacts

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| email | text unique | normalized |
| name | text | latest non-empty value seen |
| mobile | text | |
| company | text | |
| linkedin_url | text | |
| created_at, updated_at | timestamptz | |

Sync fills empty fields. It does not replace a non-empty name or company with a blank cell. A non-empty new value does update the contact. The campaign row keeps the snapshot used for that send.

## campaign_contacts

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| campaign_id | uuid fk | on delete cascade |
| contact_id | uuid fk | |
| sheet_row | int | 1-based sheet row at last sync; header is row 1 |
| name | text | editable snapshot |
| company | text | |
| role | text | editable; this is what `{{role}}` uses |
| original_role | text | unchanged sheet value |
| location | text | |
| mobile | text | |
| linkedin_url | text | |
| job_description | text | stored for a later classifier |
| notes | text | |
| profile_id | uuid fk null | detected or manually set |
| match_confidence | numeric(4,3) | null if unmatched |
| match_method | text | `keyword`, `manual`, `unmatched` |
| matched_keywords | jsonb | list of strings |
| resume_id | uuid fk null | resolved, then editable |
| template_id | uuid fk null | resolved, then editable |
| resume_overridden | bool | default false |
| template_overridden | bool | default false |
| allow_resend | bool | default false; required when history already has a send and the sheet says `NOT_SENT` |
| sheet_write_pending | bool | true when the database status is ahead of the sheet cell |
| status | text | see below |
| skip_reason | text | null |
| validation_errors | jsonb | list of strings |
| unique (campaign_id, contact_id) | | |

Changing `profile_id` re-resolves resume and template unless that field was already overridden.

Cell text from the sheet is capped at 10,000 characters.

### Contact status

| Status | When | Sheet |
| --- | --- | --- |
| `PENDING` | Valid and matched, waiting for confirm. | `NOT_SENT` |
| `NEEDS_REVIEW` | No confident profile, or resume/template missing. | `NOT_SENT`, reason in `outreach_error` |
| `QUEUED` | Run started; job not yet claimed. | stays `NOT_SENT` until the attempt finishes |
| `SENDING` | Worker holds the row lock. | stays `NOT_SENT` |
| `SENT` | Gmail accepted the message. | `SENT`, `sent_at` filled |
| `FAILED` | Permanent failure, or retries exhausted. | `NOT_SENT`, reason in `outreach_error` |
| `SKIPPED` | Duplicate, excluded, cancelled while queued, or dry run. | `NOT_SENT`, reason in `outreach_error` |

Invalid rows (bad email, missing role) are `SKIPPED` with `skip_reason=invalid`. They never enter the queue.

A row already marked `SENT` on the sheet is stored as `SENT` and is not a candidate. Dry run never writes `SENT` on the sheet or in `email_history`.

Job status and contact status are updated in one transaction.

## email_jobs

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| campaign_contact_id | uuid unique | idempotency |
| campaign_id | uuid fk | denormalized for the claim query |
| contact_id | uuid fk | |
| status | text | `QUEUED`, `SENDING`, `SENT`, `FAILED`, `SKIPPED` |
| scheduled_at | timestamptz | |
| next_attempt_at | timestamptz | null means eligible immediately |
| locked_at | timestamptz | |
| locked_by | text | worker id |
| attempt_count | int | default 0 |
| max_attempts | int | copied from settings at enqueue time; default 3 |
| last_error | text | |
| last_error_code | text | e.g. `rate_limit`, `invalid_recipient`, `auth` |
| error_retryable | bool | |
| gmail_message_id | text | null unless Gmail accepted the message |
| dry_run | bool | |
| sent_at | timestamptz | set only for a real send |
| created_at, updated_at | timestamptz | |

Index for the claim query: `(status, next_attempt_at)` where status is `QUEUED`.

## email_attempts

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| email_job_id | uuid fk | |
| attempted_at | timestamptz | |
| outcome | text | `sent`, `retry`, `failed`, `dry_run` |
| error_message | text | |
| error_code | text | |

## email_history

Written when a job reaches a terminal result that belongs on the contact timeline: real `SENT`, terminal `FAILED`, or `SKIPPED` for an operator exclude, duplicate, or cancel. A dry run does not insert a `SENT` history row.

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| email_job_id | uuid unique | |
| contact_id | uuid fk | |
| campaign_id | uuid fk | |
| recipient_email | text | normalized |
| profile_id | uuid null | |
| resume_id | uuid null | |
| template_id | uuid null | |
| subject | text | rendered subject |
| status | text | `SENT`, `FAILED`, `SKIPPED` |
| skip_reason | text | |
| error_message | text | |
| dry_run | bool | always false for rows in this table in the MVP |
| sent_at | timestamptz | |

Index: `(recipient_email, status)`.

## app_settings

Single row, id = 1. Secrets never go in this table.

| Column | Default | Notes |
| --- | --- | --- |
| emails_per_hour | 30 | sliding window of successful sends |
| delay_between_emails_seconds | 60 | minimum gap between send completions |
| max_daily_emails | 400 | UTC day |
| match_confidence_threshold | 0.800 | below this → `NEEDS_REVIEW` |
| max_attempts | 3 | |
| gmail_reconnect_required | bool | default false; set when refresh fails |
| updated_at | timestamptz | |

Environment variables supply the initial rate-limit numbers. After the seed, this row is the source of truth.
