from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            _PROJECT_ROOT / ".env",
            _BACKEND_ROOT / ".env",
        ),
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://outreach:outreach@localhost:5432/outreach"
    redis_url: str = "redis://localhost:6379/0"
    dry_run: bool = True
    storage_dir: str = str(_PROJECT_ROOT / "storage" / "resumes")
    app_encryption_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    frontend_origin: str = "http://localhost:5173"
    max_resume_bytes: int = 5_242_880
    max_sheet_rows: int = 2000
    log_level: str = "INFO"

    @field_validator("storage_dir")
    @classmethod
    def _absolute_storage_dir(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return str(path.resolve())


@lru_cache
def get_settings() -> Settings:
    return Settings()
