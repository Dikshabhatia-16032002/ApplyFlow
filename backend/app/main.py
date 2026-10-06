from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.errors import AppError
from app.api.routes.auth import router as auth_router
from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.health import router as health_router
from app.api.routes.sheet import router as sheet_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.resumes import router as resumes_router
from app.api.routes.templates import router as templates_router
from app.config import get_settings
from app.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title="Automated Job Outreach")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    def handle_app_error(_request: object, exc: AppError) -> JSONResponse:
        body: dict[str, object] = {"detail": exc.detail, "code": exc.code, **exc.extra}
        return JSONResponse(status_code=exc.status_code, content=body)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(sheet_router, prefix="/api/v1")
    app.include_router(campaigns_router, prefix="/api/v1")
    app.include_router(profiles_router, prefix="/api/v1")
    app.include_router(resumes_router, prefix="/api/v1")
    app.include_router(templates_router, prefix="/api/v1")
    return app


app = create_app()
