# Email pipeline

## Dispatch

Celery beat runs every 10 seconds and enqueues one dispatch task.

```text
dispatch
    → if no RUNNING campaign: return
    → if hourly or daily cap reached: return
    → if now < last_sent_at + delay: return
    → claim one job
    → re-check campaign is RUNNING
    → re-read the sheet cell; if SENT, skip Gmail
    → if history has SENT and allow_resend is false: skip
    → render template
    → read resume bytes from storage
    → DRY_RUN: log, write NOT_SENT / dry_run on the sheet
      else: Gmail API users.messages.send
    → write attempt, history, statuses
    → write SENT or NOT_SENT on that sheet row
```

### Claim

In one transaction:

```text
select one email_jobs row
  status = QUEUED
  next_attempt_at is null or <= now()
  campaign status = RUNNING
order by scheduled_at
for update skip locked
limit 1

set status = SENDING, locked_at = now(), locked_by = worker id
```

The send happens after that transaction commits. The completion update applies only when status is still `SENDING` and `locked_by` is this worker.

Worker concurrency is 1, on the `email` queue.

## Idempotency

- One job per campaign contact.
- If `gmail_message_id` is already set, the worker marks `SENT`, writes the sheet if needed, and does not call Gmail.
- If the sheet cell is already `SENT` when the worker is about to send, Gmail is not called.
- Crash recovery: a periodic task resets `SENDING` rows whose `locked_at` is older than 10 minutes and whose `gmail_message_id` is null back to `QUEUED`, and increments `attempt_count`. If the message id is present, it marks `SENT` and retries the sheet write if needed.

The worker stores the Gmail message id in the same step as the API response, before sheet writeback or history, so a crash after acceptance is recovered as `SENT` rather than as another send.

## Rate limits

All three settings apply together. The worker sends only when each one allows it:

- fewer than `emails_per_hour` successful sends in the past 60 minutes
- fewer than `max_daily_emails` successful sends since 00:00 UTC
- at least `delay_between_emails_seconds` since the previous successful send

Successful means Gmail accepted the message. Dry-run completions count toward these limits so a dry run exercises the scheduler. Failed attempts do not count as sends. They wait until `next_attempt_at`.

Defaults live in `app_settings`: 30 per hour, 60 seconds between sends, 400 per day.

Pause is checked before claim and again immediately before the Gmail call. If the campaign is no longer `RUNNING`, the job returns to `QUEUED`, or to `SKIPPED` / `cancelled` if the campaign is `CANCELLED`.

## Retries

| Error | Behavior |
| --- | --- |
| HTTP 429, 500, 503, timeout, connection error | Retryable. `attempt_count += 1`. Delay `60s * 2^(attempt-1)` plus a small jitter. Status returns to `QUEUED`. |
| Attempts exhausted | `FAILED`. Sheet: `NOT_SENT` and the error. |
| Invalid recipient, missing attachment, render error | `FAILED` immediately. `error_retryable = false`. |
| OAuth refresh failure, or 401 after refresh | Pause every `RUNNING` campaign. Set `gmail_reconnect_required`. Leave the job `QUEUED`. |

`max_attempts` is the total number of tries, default 3. The waits before the second and third try are about 60 seconds and 120 seconds.

## Dry run

When `DRY_RUN=true` the worker logs:

```text
Would send:
To: recruiter@example.com
Template: Full Stack Outreach
Resume: fullstack_resume.pdf
Subject: ...
```

The log includes `campaign_id`, `contact_id`, and `email_job_id`. It does not include tokens or message bodies beyond the subject line already shown to the operator in preview.

The job finishes as `SKIPPED` with `skip_reason=dry_run` and `dry_run=true`. `gmail_message_id` stays null. No `SENT` history row is written. The sheet stays `NOT_SENT` with `outreach_error=dry_run`.

The UI shows a persistent banner while the flag is on.

## Gmail client

`GmailClient.send(message) -> message_id` is the only send entry point. Tests replace it with an in-memory fake.

The real client:

1. Loads the encrypted refresh token.
2. Refreshes the access token when expiry is inside two minutes.
3. Builds a MIME message: To, Subject, plain text body, one PDF part, From as the connected account.
4. Calls `users.messages.send` with `userId=me`.
5. Returns the Gmail message id.

The client never logs token material.

## Sheets client

`SheetsClient` is the only spreadsheet entry point. Tests replace it with an in-memory fake. The real client reads and updates the configured spreadsheet id only.

- `get_values(range) -> rows`
- `ensure_status_columns(headers) -> column map`
- `update_status_cells(updates) -> none`

A call aimed at any other spreadsheet id raises before the HTTP request.
