"""Wakeups for the Postgres email queue. Concurrency stays at 1."""

import os
import socket

from app.db import SessionLocal
from app.integrations.gmail_client import get_gmail_client
from app.integrations.sheets_client import get_sheets_client
from app.services.email_service import dispatch_once, recover_stale_sends as recover_rows
from app.workers.celery_app import celery_app


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@celery_app.task(name="app.workers.email_worker.dispatch_due_email")
def dispatch_due_email() -> None:
    with SessionLocal() as session:
        dispatch_once(
            session,
            worker_id=worker_identity(),
            gmail=get_gmail_client(session),
            sheets=get_sheets_client(),
        )


@celery_app.task(name="app.workers.email_worker.recover_stale_sends")
def recover_stale_sends() -> None:
    with SessionLocal() as session:
        recover_rows(session, sheets=get_sheets_client())
        session.commit()
