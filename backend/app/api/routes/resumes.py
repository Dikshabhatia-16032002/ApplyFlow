from uuid import UUID

from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import Pagination, SessionDep
from app.config import get_settings
from app.schemas.common import Page
from app.schemas.resume import ResumeOut, ResumeUpdate
from app.services import resume_service

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.get("", response_model=Page[ResumeOut])
def list_resumes(session: SessionDep, page: Pagination) -> Page[ResumeOut]:
    limit, offset = page
    items, total = resume_service.list_resumes(session, limit=limit, offset=offset)
    return Page(items=items, limit=limit, offset=offset, total=total)


@router.post("", response_model=ResumeOut, status_code=201)
def create_resume(
    session: SessionDep,
    file: UploadFile,
    name: str = Form(""),
    is_active: bool = Form(True),
    is_default: bool = Form(False),
    profile_ids: str = Form(""),
) -> ResumeOut:
    settings = get_settings()
    data = file.file.read(settings.max_resume_bytes + 1)
    return resume_service.create_resume(
        session,
        filename=file.filename,
        data=data,
        name=name,
        is_active=is_active,
        is_default=is_default,
        profile_ids=resume_service.parse_profile_ids(profile_ids),
    )


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(resume_id: UUID, session: SessionDep) -> ResumeOut:
    return resume_service.get_resume(session, resume_id)


@router.get("/{resume_id}/file")
def download_resume(resume_id: UUID, session: SessionDep, inline: bool = False) -> FileResponse:
    path, filename = resume_service.resume_file(session, resume_id)
    disposition = "inline" if inline else "attachment"
    return FileResponse(path, media_type="application/pdf", filename=filename, content_disposition_type=disposition)


@router.patch("/{resume_id}", response_model=ResumeOut)
def update_resume(resume_id: UUID, body: ResumeUpdate, session: SessionDep) -> ResumeOut:
    return resume_service.update_resume(session, resume_id, body)


@router.post("/{resume_id}/replace", response_model=ResumeOut)
def replace_resume(resume_id: UUID, session: SessionDep, file: UploadFile) -> ResumeOut:
    settings = get_settings()
    data = file.file.read(settings.max_resume_bytes + 1)
    return resume_service.replace_resume(session, resume_id, filename=file.filename, data=data)
