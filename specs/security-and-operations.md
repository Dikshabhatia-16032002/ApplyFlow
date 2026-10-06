# Security and operations

## Configuration

`.env` is gitignored. `.env.example` ships with empty secrets and safe defaults.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres |
| `REDIS_URL` | Celery broker and result backend |
| `DRY_RUN` | `true` or `false` |
| `STORAGE_DIR` | Resume file root |
| `APP_ENCRYPTION_KEY` | Fernet key for OAuth tokens |
| `GOOGLE_CLIENT_ID` | OAuth client |
| `GOOGLE_CLIENT_SECRET` | OAuth client |
| `GOOGLE_REDIRECT_URI` | Callback URL |
| `FRONTEND_ORIGIN` | CORS and the post-login redirect |
| `MAX_RESUME_BYTES` | Default 5242880 |
| `MAX_SHEET_ROWS` | Default 2000 |
| `LOG_LEVEL` | Default `INFO` |

Initial rate-limit numbers in `.env.example` are written into `app_settings` by the seed. After that, Settings is the source of truth.

## Security

- Google access is OAuth. The app does not ask for or store a mailbox password.
- Tokens are encrypted at rest. Logs and API responses omit them.
- Resume URLs are API routes, not a public static directory.
- A resume must be a PDF: extension, size, and a body that starts with `%PDF`.
- The Sheets client accepts only the saved spreadsheet id.
- Sheet cells are data. They are not interpolated into SQL. The app reads calculated values and does not execute sheet content.
- String limits: subject 200, template body 20,000, sheet cell text 10,000.
- Pydantic schemas validate every write endpoint.
- CORS is limited to `FRONTEND_ORIGIN`.
- `.gitignore` includes `.env`, `credentials.json`, token files, `storage/resumes/*`, and `__pycache__`.

## Reliability

| Failure | Behavior |
| --- | --- |
| Gmail 5xx or 429 | Retry with backoff, then `FAILED` and `NOT_SENT` on the sheet |
| Expired access token | Refresh. On failure, pause running campaigns and ask to reconnect |
| Redis down | `/health` reports it. Sends do not start. Queued rows remain |
| Postgres down | API returns 503. The worker retries the task |
| Duplicate Start | Unique job constraint. No second email |
| Sheet already says `SENT` | Worker skips the Gmail call |
| Sheet write fails after a successful send | Job stays `SENT`. The cell write is retried. Mail is not sent again |
| Sheet missing, or the account is not an Editor | Sync returns an error. No rows are queued |
| Invalid email | That row is `NOT_SENT` on the sheet. The rest of the sync continues |
| Missing resume or template | Row stays `NEEDS_REVIEW`. Confirm is rejected until it is fixed or excluded |
| Worker crash during `SENDING` | Stale-lock recovery in [email-pipeline.md](email-pipeline.md) |
| Operator pauses | The worker stops claiming within one tick |

## Logging

Structured JSON logs.

Fields when an email is involved: `campaign_id`, `contact_id`, `email_job_id`, `recipient`, `status`, `timestamp`, `error`.

Never log access tokens, refresh tokens, the client secret, the encryption key, raw Authorization headers, or resume bytes.

## Tests

Pytest. The Gmail client and the Sheets client are fakes. No test calls Google.

| Test | Asserts |
| --- | --- |
| Sheet sync | Aliases, row cap, `SENT` rows left untouched, status columns created once |
| Row validation | Bad email, missing role, duplicate in the sheet |
| Writeback | A real send writes `SENT` and `sent_at`. Failure and dry run write `NOT_SENT` plus a reason. A second write does not call Gmail |
| Keyword matcher | Examples in [profile-matching.md](profile-matching.md). A tie or low confidence becomes review. Inactive profiles are ignored |
| Template render | Variables replaced. Unknown token warned. Empty value warned |
| Duplicate protection | Sheet `SENT` skips. A row set back to `NOT_SENT` queues only with `allow_resend` |
| Resume selection | Profile resume, else default, else needs review |
| Queue creation | One job per pending contact. A second start is a no-op |
| Retries | 503 requeues with a later `next_attempt_at`. An invalid recipient fails once. A fourth attempt does not happen |
| Dry run | The fake Gmail send is not called. The sheet fake receives `NOT_SENT` / `dry_run` |

Matcher and renderer tests do not need Postgres. Service tests that need transactions use Postgres, so `SKIP LOCKED` is real in at least one integration test.

## Docker

Phase 9 adds Compose. Earlier phases may run the API, Postgres, and a worker directly.

| Service | Role |
| --- | --- |
| `postgres` | Database |
| `redis` | Broker |
| `api` | Uvicorn |
| `worker` | Celery worker, concurrency 1, queue `email` |
| `beat` | Celery beat, 10 second dispatch |
| `frontend` | Vite dev server in development |

The same process layout is what a later cloud deploy would run: a stateless API, one sender, managed Postgres, managed Redis, and object storage behind `storage_key`. Object storage is not in the MVP. The local volume is.
