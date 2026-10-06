from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Pagination, SessionDep
from app.schemas.campaign import CampaignContactOut, CampaignOut, ContactMatchUpdate
from app.schemas.common import Page
from app.schemas.sheet import HeaderMapInput, SyncSummary
from app.services import campaign_contact_service, campaign_service, sheet_sync_service

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=Page[CampaignOut])
def get_campaigns(session: SessionDep, page: Pagination) -> Page[CampaignOut]:
    limit, offset = page
    return campaign_contact_service.list_campaigns(session, limit=limit, offset=offset)


@router.post("/{campaign_id}/confirm", response_model=CampaignOut)
def confirm_campaign(campaign_id: UUID, session: SessionDep) -> CampaignOut:
    return campaign_service.confirm_campaign(session, campaign_id)


@router.post("/{campaign_id}/start", response_model=CampaignOut)
def start_campaign(campaign_id: UUID, session: SessionDep) -> CampaignOut:
    return campaign_service.start_campaign(session, campaign_id)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
def pause_campaign(campaign_id: UUID, session: SessionDep) -> CampaignOut:
    return campaign_service.pause_campaign(session, campaign_id)


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
def resume_campaign(campaign_id: UUID, session: SessionDep) -> CampaignOut:
    return campaign_service.resume_campaign(session, campaign_id)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
def cancel_campaign(campaign_id: UUID, session: SessionDep) -> CampaignOut:
    return campaign_service.cancel_campaign(session, campaign_id)


@router.get("/{campaign_id}/contacts", response_model=Page[CampaignContactOut])
def get_contacts(campaign_id: UUID, session: SessionDep, page: Pagination) -> Page[CampaignContactOut]:
    limit, offset = page
    return campaign_contact_service.list_contacts(session, campaign_id, limit=limit, offset=offset)


@router.patch("/{campaign_id}/contacts/{contact_row_id}", response_model=CampaignContactOut)
def update_contact(
    campaign_id: UUID,
    contact_row_id: UUID,
    body: ContactMatchUpdate,
    session: SessionDep,
) -> CampaignContactOut:
    return campaign_contact_service.update_match(session, campaign_id, contact_row_id, body)


@router.post("/{campaign_id}/mapping", response_model=SyncSummary)
def save_mapping(campaign_id: UUID, body: HeaderMapInput, session: SessionDep) -> SyncSummary:
    return sheet_sync_service.save_mapping_and_sync(session, campaign_id, body)
