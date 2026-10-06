from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.sheet import SheetOut, SheetPut, SyncSummary
from app.services import sheet_sync_service

router = APIRouter(prefix="/sheet", tags=["sheet"])


@router.get("", response_model=SheetOut)
def get_sheet(session: SessionDep) -> SheetOut:
    return sheet_sync_service.get_sheet(session)


@router.put("", response_model=SheetOut)
def save_sheet(body: SheetPut, session: SessionDep) -> SheetOut:
    return sheet_sync_service.save_sheet(session, body.url, body.sheet_name)


@router.post("/sync", response_model=SyncSummary)
def sync_sheet(session: SessionDep) -> SyncSummary:
    return sheet_sync_service.sync_sheet(session)
