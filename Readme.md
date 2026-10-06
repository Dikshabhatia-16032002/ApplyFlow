# Run

`DRY_RUN=false` in `.env` sends real mail from the connected Gmail account. `DRY_RUN=true` runs the same steps and writes `NOT_SENT` / `dry_run` on the sheet.

Open four terminals and leave each one running.

1. Database and Redis:

```bash
cd "<Your project folder>"
docker compose up -d
docker start outreach-redis || docker run --name outreach-redis -p 6379:6379 -d redis:7
```

2. API:

```bash
cd "<Your project folder>backend"
uv run uvicorn app.main:app --reload
```

3. Worker:

```bash
cd "<Your project folder>/backend"
uv run celery -A app.workers.celery_app worker --beat -Q email --concurrency=1
```

4. Website:

```bash
cd "<Your project folder>/frontend"
npm run dev
```

5. Open http://localhost:5173/. Connect Google once from the header if it is not already connected. The sheet must be shared as Editor with that account.

6. Each time a batch should go out:

```bash
cd "<Your project folder>/backend"
uv run python scripts/start_send.py
```

That syncs the sheet, confirms the draft, and starts sending. The first email goes out within about 10 seconds. Each following row waits 60 seconds. Rows already marked `SENT` are skipped. If a row needs review, the script stops until that row is resolved on the Sheet page.

Postgres is `localhost:5432`, database `outreach`, user `outreach`, password `outreach`. Redis on port `6379` only wakes the worker.
