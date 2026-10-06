from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Pagination, SessionDep
from app.schemas.common import Page
from app.schemas.template import TemplateCreate, TemplateOut, TemplatePreviewOut, TemplatePreviewRequest, TemplateUpdate
from app.services import template_service

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=Page[TemplateOut])
def list_templates(session: SessionDep, page: Pagination) -> Page[TemplateOut]:
    limit, offset = page
    items, total = template_service.list_templates(session, limit=limit, offset=offset)
    return Page(items=items, limit=limit, offset=offset, total=total)


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateCreate, session: SessionDep) -> TemplateOut:
    return template_service.create_template(session, body)


@router.post("/preview", response_model=TemplatePreviewOut)
def preview_template(body: TemplatePreviewRequest, session: SessionDep) -> TemplatePreviewOut:
    return template_service.preview_template(session, body)


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: UUID, session: SessionDep) -> TemplateOut:
    return template_service.get_template(session, template_id)


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(template_id: UUID, body: TemplateUpdate, session: SessionDep) -> TemplateOut:
    return template_service.update_template(session, template_id, body)


@router.delete("/{template_id}", response_model=TemplateOut)
def deactivate_template(template_id: UUID, session: SessionDep) -> TemplateOut:
    return template_service.deactivate_template(session, template_id)


@router.post("/{template_id}/duplicate", response_model=TemplateOut, status_code=201)
def duplicate_template(template_id: UUID, session: SessionDep) -> TemplateOut:
    return template_service.duplicate_template(session, template_id)
