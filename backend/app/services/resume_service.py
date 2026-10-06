import hashlib
import logging
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import get_settings
from app.models import Resume
from app.schemas.resume import ResumeOut, ResumeUpdate
from app.services.catalog_common import (
    apply_active_and_default,
    assign_profiles,
    profile_ids_for,
    raise_integrity,
    require_resume,
)

logger = logging.getLogger(__name__)


def _out(session: Session, resume: Resume) -> ResumeOut:
    return ResumeOut(
        id=resume.id,
        name=resume.name,
        original_filename=resume.original_filename,
        content_type=resume.content_type,
        size_bytes=resume.size_bytes,
        sha256=resume.sha256,
        is_active=resume.is_active,
        is_default=resume.is_default,
        profile_ids=profile_ids_for(session, "resume_id", resume.id),
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


def list_resumes(session: Session, *, limit: int, offset: int) -> tuple[list[ResumeOut], int]:
    total = session.scalar(select(func.count()).select_from(Resume)) or 0
    rows = session.scalars(select(Resume).order_by(Resume.name).limit(limit).offset(offset)).all()
    return [_out(session, row) for row in rows], total


def get_resume(session: Session, resume_id: UUID) -> ResumeOut:
    return _out(session, require_resume(session, resume_id))


def resume_file(session: Session, resume_id: UUID) -> tuple[Path, str]:
    resume = require_resume(session, resume_id)
    root = Path(get_settings().storage_dir).resolve()
    key = resume.storage_key
    if Path(key).name != key:
        raise AppError(404, "file_missing", "Resume file is missing")
    path = (root / key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError(404, "file_missing", "Resume file is missing")
    return path, resume.original_filename


def create_resume(
    session: Session,
    *,
    filename: str | None,
    data: bytes,
    name: str,
    is_active: bool,
    is_default: bool,
    profile_ids: list[UUID],
) -> ResumeOut:
    settings = get_settings()
    if len(data) > settings.max_resume_bytes:
        raise AppError(413, "file_too_large", f"Resume exceeds the {settings.max_resume_bytes} byte limit")
    original = _pdf_filename(filename, data)
    label = _display_name(name, original)
    if is_default and not is_active:
        raise AppError(409, "inactive_default", "An inactive resume cannot be the default")
    key, digest = _write_pdf(data)
    committed = False
    try:
        resume = Resume(
            name=label,
            original_filename=original,
            storage_key=key,
            content_type="application/pdf",
            size_bytes=len(data),
            sha256=digest,
            is_active=is_active,
            is_default=False,
        )
        session.add(resume)
        session.flush()
        if profile_ids:
            assign_profiles(session, column="resume_id", owner_id=resume.id, profile_ids=profile_ids)
        apply_active_and_default(
            session,
            Resume,
            resume,
            is_active=is_active,
            is_default=is_default,
            noun="resume",
        )
        session.commit()
        committed = True
        session.refresh(resume)
        return _out(session, resume)
    except IntegrityError as exc:
        if not committed:
            session.rollback()
            _unlink(key)
        raise_integrity(exc, name_message="A resume with that name already exists")
    except Exception:
        if not committed:
            session.rollback()
            _unlink(key)
        raise


def update_resume(session: Session, resume_id: UUID, body: ResumeUpdate) -> ResumeOut:
    resume = require_resume(session, resume_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        label = str(changes["name"]).strip()
        if not label:
            raise AppError(422, "invalid_name", "Name is required")
        resume.name = label
    apply_active_and_default(
        session,
        Resume,
        resume,
        is_active=changes["is_active"] if "is_active" in changes else None,
        is_default=changes["is_default"] if "is_default" in changes else None,
        noun="resume",
    )
    if "profile_ids" in changes:
        assign_profiles(session, column="resume_id", owner_id=resume.id, profile_ids=changes["profile_ids"])
    try:
        session.flush()
    except IntegrityError as exc:
        raise_integrity(exc, name_message="A resume with that name already exists")
    session.refresh(resume)
    return _out(session, resume)


def replace_resume(session: Session, resume_id: UUID, *, filename: str | None, data: bytes) -> ResumeOut:
    settings = get_settings()
    if len(data) > settings.max_resume_bytes:
        raise AppError(413, "file_too_large", f"Resume exceeds the {settings.max_resume_bytes} byte limit")
    resume = require_resume(session, resume_id)
    original = _pdf_filename(filename, data)
    new_key, digest = _write_pdf(data)
    old_key = resume.storage_key
    committed = False
    try:
        resume.original_filename = original
        resume.storage_key = new_key
        resume.content_type = "application/pdf"
        resume.size_bytes = len(data)
        resume.sha256 = digest
        session.commit()
        committed = True
        session.refresh(resume)
    except Exception:
        if not committed:
            session.rollback()
            _unlink(new_key)
        raise
    if old_key != new_key:
        _unlink(old_key)
    return _out(session, resume)


def parse_profile_ids(raw: str) -> list[UUID]:
    if not raw.strip():
        return []
    parsed: list[UUID] = []
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            parsed.append(UUID(piece))
        except ValueError as exc:
            raise AppError(422, "invalid_profile_ids", "profile_ids must be comma-separated UUIDs") from exc
    return parsed


def _pdf_filename(filename: str | None, data: bytes) -> str:
    if not filename or not filename.strip():
        raise AppError(422, "invalid_pdf", "Resume must use a .pdf extension")
    original = Path(filename).name.strip()
    if original in {"", ".", ".."} or not original.lower().endswith(".pdf"):
        raise AppError(422, "invalid_pdf", "Resume must use a .pdf extension")
    if not data.startswith(b"%PDF"):
        raise AppError(422, "invalid_pdf", "Resume file must start with %PDF")
    return original[:255]


def _display_name(raw_name: str, original: str) -> str:
    label = raw_name.strip()
    if not label:
        label = Path(original).stem.strip() or "Resume"
    if len(label) > 200:
        raise AppError(422, "invalid_name", "Name must be 200 characters or fewer")
    return label


def _write_pdf(data: bytes) -> tuple[str, str]:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = f"{uuid4()}.pdf"
    (root / key).write_bytes(data)
    return key, hashlib.sha256(data).hexdigest()


def _unlink(key: str) -> None:
    path = Path(get_settings().storage_dir).resolve() / key
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove resume file %s", key)
