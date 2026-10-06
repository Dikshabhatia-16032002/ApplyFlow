# Spec index

Status: **proposal, awaiting approval before Phase 1**

Automated job outreach for one operator. The app reads recruiter contacts from one Google Sheet, matches each row to a job profile, selects that profile’s resume and email template, previews the message, and sends it through Gmail. The same sheet is marked `SENT` or `NOT_SENT`.

There is no contact-file upload. AI classification and AI personalization are extension points only.

| Spec | Contents |
| --- | --- |
| [architecture.md](architecture.md) | Workflow, system shape, folder layout, future AI hooks |
| [data-model.md](data-model.md) | Tables, relationships, statuses |
| [google-sheet.md](google-sheet.md) | The shared sheet, columns, sync, validation, writeback |
| [profile-matching.md](profile-matching.md) | Keyword matcher, resume and template selection, preview |
| [email-pipeline.md](email-pipeline.md) | Queue, rate limits, retries, dry run, Gmail and Sheets clients |
| [api.md](api.md) | REST endpoints |
| [frontend.md](frontend.md) | Screens and UI responsibilities |
| [security-and-operations.md](security-and-operations.md) | Config, security, reliability, logging, tests, Docker |
| [implementation-plan.md](implementation-plan.md) | Phases 1–10 and what is out of scope |

## Decisions locked for the MVP

| Topic | Decision |
| --- | --- |
| Who uses it | One operator on a machine you control. A `users` row exists so later multi-user work does not require a schema rewrite. There is no signup, password, or team model. |
| App access | API and UI are for local use. The secret that matters is the Google grant, not an app login. |
| Sending identity | Mail is sent as the connected Gmail account. Names in the subject or signature live in the template. |
| Google access | One OAuth grant: Gmail send and Google Sheets. The sheet is shared as Editor with that same account. |
| Contact source | One spreadsheet URL. First tab, unless a tab name is saved. |
| Required columns | A valid email, and a role/title column. |
| Status columns | The app owns `outreach_status`, `sent_at`, `detected_profile`, `resume_name`, `template_name`, and `outreach_error`. |
| Match input | The role cell only. The job description is stored and unused by the keyword matcher. |
| Uncertain match | `NEEDS_REVIEW` in the app. The sheet shows `NOT_SENT`. The row is not queued. |
| Already sent | A sheet cell of `SENT` is never sent again. Changing it to `NOT_SENT` is a resend request and still needs an explicit allow in the preview. |
| Start rule | Confirm is blocked while any included row needs review. |
| Rate limits | Settings in the database. Defaults: 30/hour, 60 seconds between sends, 400/day, 3 attempts. |
| Concurrency | One sender. |
| Dry run | `DRY_RUN=true` runs the workflow and writes the sheet as `NOT_SENT` / `dry_run`. Gmail send is not called. |
| Resumes | PDF only, one attachment, max 5 MB. |
| Body | Plain text. |
| Row cap | 2,000 data rows per sync. |
| Time | Stored in UTC. `sent_at` on the sheet is ISO-8601 UTC. |

## Approval

Phase 1 starts only after an explicit go-ahead. Change any row in the table above before that if you want a different default.
