"""Celery app. Beat enqueues one dispatch task every 10 seconds on the email queue."""

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery("outreach", broker=settings.redis_url)
celery_app.conf.update(
    task_default_queue="email",
    task_ignore_result=True,
    worker_concurrency=1,
    # Prefork children never receive the tracer setup, so every task dies with
    # "not enough values to unpack (expected 3, got 0)". One sender does not need a fork.
    worker_pool="solo",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-email": {
            "task": "app.workers.email_worker.dispatch_due_email",
            "schedule": 10.0,
            "options": {"queue": "email"},
        },
        "recover-stale-sends": {
            "task": "app.workers.email_worker.recover_stale_sends",
            "schedule": 60.0,
            "options": {"queue": "email"},
        },
    },
)

import app.workers.email_worker  # noqa: E402, F401
