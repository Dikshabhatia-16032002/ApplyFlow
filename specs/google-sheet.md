# Google Sheet

The operator pastes one Google Sheets URL. The app parses the spreadsheet id and uses the first tab unless a tab name is saved. The connected Google account must have Editor access on that sheet.

There is no CSV or XLSX contact import, and there is no second spreadsheet.

## Read

Sync uses the Sheets API (`spreadsheets.values.get`). Formulas come back as their calculated values. The app does not evaluate expressions.

Limits:

- 2,000 data rows (`MAX_SHEET_ROWS`).
- A header-only sheet is an error.
- Each cell stored by the app is capped at 10,000 characters.

Sync is refused while a run is `RUNNING` or `PAUSED`, so a refresh cannot reset rows that are already queued.

## Status columns

On the first sync, any missing header below is appended to the right of the existing headers. The app does not insert columns in the middle and does not change contact cells.

| Column | Values |
| --- | --- |
| `outreach_status` | `SENT` or `NOT_SENT` |
| `sent_at` | ISO-8601 UTC when the status becomes `SENT`. Cleared when the operator sets the row back to `NOT_SENT` and a later run has not sent it. |
| `detected_profile` | profile name, or blank |
| `resume_name` | resume name used, or blank |
| `template_name` | template name used, or blank |
| `outreach_error` | blank when sent; otherwise a short reason |

`SENT` means the email went out. Every other outcome is `NOT_SENT`, with the reason in `outreach_error`:

```text
needs_review
invalid_email
missing_role
duplicate_in_sheet
malformed
excluded_by_user
cancelled
failed: <short message>
dry_run
```

Writeback uses `spreadsheets.values.batchUpdate` on those columns only. Columns are found by header name on each sync, so a reordered sheet still updates the right cells. If a status header was deleted, the next sync appends it again.

Before a real send, the worker re-reads that row’s `outreach_status`. If the cell is already `SENT`, Gmail is not called.

If the Sheets write fails after Gmail has accepted the message, the job stays `SENT` in the database, `sheet_write_pending` is set, and a later tick retries the cell write. It does not send a second email.

After matching, the app writes `outreach_status` for every row that is not already `SENT`. Existing `SENT` cells are left unchanged, including `sent_at` and the other status columns on that row.

## Contact headers

Aliases are matched after the same normalization used for keywords: lowercase, punctuation to spaces, collapsed whitespace.

| Field | Accepted headers |
| --- | --- |
| name | name, full_name, fullname, contact_name, recruiter_name |
| email | email, e_mail, email_address, mail |
| mobile | mobile, phone, phone_number, contact_number |
| company | company, company_name, organization, organisation |
| role | role, profile, title, job_title, position, job_role |
| job_description | job_description, jd, description |
| location | location, city, job_location |
| linkedin_url | linkedin_url, linkedin, linkedin_profile |
| notes | notes, note, comments |

If both `email` and `role` map, unknown columns are ignored. If either is missing, the API returns the detected headers and does not create contacts. The UI posts an explicit mapping, which is stored on `sheet_connection.header_map`, and sync runs again.

## Row validation

| Check | Result |
| --- | --- |
| Email missing, or not one `@`, a dotted domain, and no spaces | `SKIPPED` / `invalid`. Sheet: `NOT_SENT`, `invalid_email` or `missing_role` as appropriate. |
| Role blank | `SKIPPED` / `invalid` |
| Same email already kept from this sheet | `SKIPPED` / `duplicate_in_sheet`. First valid row wins. |
| `outreach_status` is already `SENT` | Stored as `SENT`. Not a candidate. Sheet cells for that row stay as they are. |
| Operator changed a previously sent row to `NOT_SENT` | Shown in the preview with the earlier send. Queued only when `allow_resend` is set. |
| Row cannot be read | `SKIPPED` / `malformed` |

Email validation is a format check, not a mailbox probe.

The sync response is a summary, not a send:

```text
rows_read, valid, needs_review, not_sent, already_sent, skipped_invalid, skipped_duplicate
```

The new run remains `DRAFT`.

## Identity across edits

Rows are matched to existing contacts by normalized email. `sheet_row` is the row index at last sync and is the first place writeback looks. If that row no longer has the same email, writeback searches the `email` column and updates the row it finds. If the email is gone, `sheet_write_pending` stays true and the run screen can retry after the next sync.
