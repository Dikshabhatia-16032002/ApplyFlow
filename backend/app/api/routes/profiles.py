from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Pagination, SessionDep
from app.schemas.common import Page
from app.schemas.profile import KeywordReplace, ProfileCreate, ProfileOut, ProfileUpdate
from app.services import profile_service

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=Page[ProfileOut])
def list_profiles(session: SessionDep, page: Pagination) -> Page[ProfileOut]:
    limit, offset = page
    items, total = profile_service.list_profiles(session, limit=limit, offset=offset)
    return Page(items=items, limit=limit, offset=offset, total=total)


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(body: ProfileCreate, session: SessionDep) -> ProfileOut:
    return profile_service.create_profile(session, body)


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: UUID, session: SessionDep) -> ProfileOut:
    return profile_service.get_profile(session, profile_id)


@router.patch("/{profile_id}", response_model=ProfileOut)
def update_profile(profile_id: UUID, body: ProfileUpdate, session: SessionDep) -> ProfileOut:
    return profile_service.update_profile(session, profile_id, body)


@router.delete("/{profile_id}", response_model=ProfileOut)
def deactivate_profile(profile_id: UUID, session: SessionDep) -> ProfileOut:
    return profile_service.deactivate_profile(session, profile_id)


@router.put("/{profile_id}/keywords", response_model=ProfileOut)
def replace_keywords(profile_id: UUID, body: KeywordReplace, session: SessionDep) -> ProfileOut:
    return profile_service.replace_keywords(session, profile_id, body)
