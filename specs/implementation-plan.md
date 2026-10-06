# Implementation plan

Each phase ends in a review before the next one starts. Phase 1 starts only after the spec index is approved.

## Phase 1 — Project setup and database

Backend package, settings, logging, SQLAlchemy models, and an Alembic migration for every table in [data-model.md](data-model.md). Seed the single user, the seven profiles, their keywords, and default `app_settings`.

Docker in this phase is limited to Postgres if a local database is inconvenient. Full Compose waits until Phase 9. The health check reports the database.

Done when the migration applies on an empty database, the seed is idempotent, and the models match the data-model spec.

## Phase 2 — Profiles, resumes, templates

CRUD services and routes. PDF upload, replace, download, default flag, and profile assignment. Template duplicate and render preview. Frontend pages for Profiles, Resumes, and Templates.

Done when the operator can create the catalog the matcher and the sender will use. There is no send path yet.

## Phase 3 — Sheet sync and validation

Save the one sheet URL, read it through a fake Sheets client, map headers, validate rows, upsert contacts, and show the summary. Status-column writeback may be a stub until Phase 6. The UI must not offer a contact-file upload.

Done when a fixture sheet produces the right skip reasons, leaves existing `SENT` rows alone, opens a `DRAFT` run, and queues nothing.

## Phase 4 — Profile matching

`KeywordProfileMatcher` wired into sync. A manual profile change re-resolves resume and template. Tests cover the examples in [profile-matching.md](profile-matching.md).

Done when uncertain rows are `NEEDS_REVIEW` and confident rows show the expected profile, resume, and template.

## Phase 5 — Preview and confirm

Review table, row editor, rendered preview, exclude, and confirm to `READY`. Hide Start until Phase 6.

Done when the operator can correct a needs-review row and confirm, and confirm is rejected while a review row remains included.

## Phase 6 — Google OAuth and send

OAuth routes for Gmail send and Spreadsheets, encrypted token storage, `GmailClient`, `SheetsClient`, the dry-run path, enqueue on Start, and a synchronous send of a single job from a service method. The worker loop is Phase 7. This phase writes status, history, and the sheet cell.

Done when a dry run completes a one-row run without calling Gmail and writes `NOT_SENT` / `dry_run` on the sheet fake, and a real send writes `SENT` only with a connected account and `DRY_RUN=false`.

## Phase 7 — Queue, rate limit, pause

Celery worker and beat, the claim query, limits, backoff, stale-lock recovery, and pause, resume, and cancel.

Done when a multi-row dry run respects the delay, pause stops the next claim, and a forced retryable error requeues once.

## Phase 8 — Dashboard, history, sheet marks

Dashboard aggregates, contact search and timeline, the settings page wired to `app_settings`, and a visible `SENT` / `NOT_SENT` count that matches the sheet. Failed sheet writes can be retried from the run screen.

Done when the operator can find a person, see earlier sends, filter the list, and the shared sheet shows who was sent and who was not.

## Phase 9 — Tests and Docker

Fill any missing tests from [security-and-operations.md](security-and-operations.md). Add `docker-compose.yml`, `.env.example`, `.gitignore`, and a README with setup, OAuth client setup, and dry-run instructions.

Done when `docker compose up` brings up the stack and the automated tests pass without sending mail.

## Phase 10 — Optional AI

Out of scope until Phases 1–9 are accepted. Requires a separate spec for the provider, the prompt, and what is stored. The extension points are described in [architecture.md](architecture.md).

## Out of scope for the MVP

- CSV or XLSX contact upload, and more than one spreadsheet
- Multiple Gmail accounts, shared inboxes, or send-as aliases
- HTML templates, inline images, or attachments other than one PDF
- Open and click tracking
- A public signup flow or roles
- Follow-up sequences
- LLM classification, job-description parsing, and an AI intro
- Deploying to a cloud provider
