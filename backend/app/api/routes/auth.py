from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.api.deps import SessionDep
from app.api.errors import AppError
from app.schemas.auth import AuthorizationOut, GoogleStatusOut
from app.services import google_oauth

router = APIRouter(prefix="/auth/google", tags=["auth"])


@router.get("/start", response_model=AuthorizationOut)
def start_google() -> AuthorizationOut:
    return AuthorizationOut(authorization_url=google_oauth.authorization_url())


@router.get("/callback")
def google_callback(session: SessionDep, code: str = "", state: str = "") -> RedirectResponse:
    try:
        if not code:
            raise AppError(400, "oauth_exchange_failed", "Google did not accept the sign-in")
        google_oauth.connect_from_callback(session, code, state)
    except AppError as exc:
        return RedirectResponse(google_oauth.frontend_redirect(f"?google_error={exc.code}"))
    return RedirectResponse(google_oauth.frontend_redirect("?google=connected"))


@router.get("/status", response_model=GoogleStatusOut)
def google_status(session: SessionDep) -> GoogleStatusOut:
    return GoogleStatusOut.model_validate(google_oauth.connection_status(session))


@router.post("/disconnect", response_model=GoogleStatusOut)
def google_disconnect(session: SessionDep) -> GoogleStatusOut:
    return GoogleStatusOut.model_validate(google_oauth.disconnect(session))
