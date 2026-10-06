# Architecture

## Workflow

```text
Connect one Google Sheet
      ↓
Sync rows
      ↓
Validate records
      ↓
Match role → profile (keyword rules)
      ↓
Select that profile’s resume and template
      ↓
Write the current mark on each row (SENT stays SENT, everyone else is NOT_SENT)
      ↓
Preview and edit
      ↓
Confirm
      ↓
Queue one email job per approved contact
      ↓
Worker sends through Gmail, rate-limited
      ↓
Update that row: SENT, or NOT_SENT with the reason
```

Nothing is sent because the sheet was synced. Sending starts only after the operator reviews the preview and starts the run. The sheet is updated again as each address finishes.

## Run lifecycle

A campaign row is one review-and-send pass over the rows that are still `NOT_SENT`. Adding rows to the sheet later is a new sync and, when those rows should go out, a new run.

```text
DRAFT → READY → RUNNING → COMPLETED
                  │  ▲
                  ▼  │
                PAUSED
                  │
                  ▼
              CANCELLED
```

| Status | Meaning |
| --- | --- |
| `DRAFT` | Sheet synced. The operator is still validating, matching, and editing. |
| `READY` | Preview confirmed. Every included row can be sent, or has been excluded on purpose. |
| `RUNNING` | The worker may claim jobs. |
| `PAUSED` | The worker stops claiming. `QUEUED` jobs stay queued. |
| `COMPLETED` | Nothing left in `QUEUED` or `SENDING`. |
| `CANCELLED` | Remaining `QUEUED` jobs become `SKIPPED` / `cancelled`. A send already in flight is allowed to finish. |

`DRAFT → READY` is confirm. `READY → RUNNING` is start. Resume goes `PAUSED → RUNNING`.

## Processes

```text
Browser (React)
    │  REST /api/v1
    ▼
FastAPI
    │
    ├── services        business rules
    ├── repositories    SQLAlchemy queries
    ├── integrations    Gmail client and Sheets client (both mockable)
    │
    ├── PostgreSQL      source of truth, including the queue
    └── Redis + Celery  wake the worker; the queue of record stays in Postgres

Worker
    claim one due job  →  rate limiter  →  render  →  Gmail or dry-run log
                       →  write SENT or NOT_SENT on that sheet row
```

The same Google OAuth grant covers Gmail send and this one spreadsheet. The Sheets client refuses every other spreadsheet id.

If Redis is down, no new send starts, and rows already in Postgres stay queued. Restarting a worker does not create a second send for a job that already has a Gmail message id.

Route handlers validate input, call a service, and map the result to HTTP. Business rules do not live in routes.

## Replaceable matching

```text
ProfileMatcher
    match(role, job_description) -> MatchResult

KeywordProfileMatcher     MVP
LlmProfileMatcher         later, same result type
```

Callers store `profile_id`, `confidence`, `method`, and `needs_review`. They do not know which implementation ran.

## Replaceable rendering

```text
render(template, contact) -> subject, body
```

The MVP renderer replaces variables and records which ones were empty. It does not call a model.

Later, if a template contains `{{ai_intro}}`, a personalizer may fill that slot only. The approved subject and body stay in place. If the personalizer is off or fails, the placeholder is removed and the approved template is what would be sent.

## Repository layout

```text
.
├── PROJECT_SPEC.md
├── specs/
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── backend/
│   ├── alembic.ini
│   ├── alembic/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── db.py
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   └── routes/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   │   ├── campaign_service.py
│   │   │   ├── contact_service.py
│   │   │   ├── sheet_sync_service.py
│   │   │   ├── profile_matcher.py
│   │   │   ├── template_service.py
│   │   │   ├── resume_service.py
│   │   │   ├── email_service.py
│   │   │   └── settings_service.py
│   │   ├── integrations/
│   │   │   ├── gmail_client.py
│   │   │   └── sheets_client.py
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   └── email_worker.py
│   │   └── utils/
│   └── tests/
│       ├── test_sheet_sync.py
│       ├── test_profile_matcher.py
│       ├── test_template_render.py
│       ├── test_duplicates.py
│       ├── test_resume_selection.py
│       ├── test_queue.py
│       └── test_retries.py
├── frontend/
│   └── src/
│       ├── api/
│       ├── components/
│       ├── pages/
│       └── types/
└── storage/                  gitignored contents
    └── resumes/
```

`storage/` is a Docker volume. The database stores a relative key, not an absolute machine path.

## Stack

| Layer | Choice |
| --- | --- |
| UI | React, TypeScript, Tailwind, Vite, React Router, TanStack Query |
| API | Python, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic |
| Database | PostgreSQL |
| Queue wakeups | Redis, Celery |
| Mail | Gmail API, OAuth 2.0, scope `gmail.send` |
| Sheet | Google Sheets API v4, scope `spreadsheets` |
| Run | Docker Compose in Phase 9 |

## Future AI

These can be added without changing campaign or job tables. They are not part of Phases 1–9. No model client, prompt, or API key is added before a separate spec for the provider.

**Classifier.** A new `ProfileMatcher`. Persist `match_method=llm` and confidence. The threshold and tie rules stay. Low confidence still means `NEEDS_REVIEW`.

**Personalizer.** Fills `{{ai_intro}}` with one or two sentences inside an approved template.

**Job description.** Pass `job_description` into the matcher. The keyword matcher continues to ignore it.
