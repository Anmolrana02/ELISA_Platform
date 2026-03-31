# Paste contents from the generated core/config.py here
# backend/core/config.py
"""
Central configuration for the ELISA Platform backend.
Reads from environment variables / .env file via pydantic-settings.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str  # postgresql+asyncpg://...

    # ── Auth ──────────────────────────────────────────────────────────────────
    jwt_secret: str
    jwt_expire_days: int = 30
    jwt_algorithm: str = "HS256"

    # ── OTP (Fast2SMS) ────────────────────────────────────────────────────────
    fast2sms_api_key: str = ""
    otp_expire_minutes: int = 10

    # ── WhatsApp (Meta Cloud API) ─────────────────────────────────────────────
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v20.0"

    # ── ELISA ML core ─────────────────────────────────────────────────────────
    # Absolute path to the elisa2/ directory on the server.
    # Defaults to sibling directory in the monorepo.
    elisa2_path: Optional[str] = None

    @property
    def elisa2_root(self) -> Path:
        if self.elisa2_path:
            return Path(self.elisa2_path)
        # Default: monorepo layout — elisa2/ is sibling of backend/
        return Path(__file__).parent.parent.parent / "elisa2"

    # ── GEE (forwarded to elisa2 settings) ───────────────────────────────────
    gee_enabled: bool = False
    gee_service_account: Optional[str] = None
    gee_key_file: Optional[str] = None

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:5173", "https://localhost:5173"]
    log_level: str = "INFO"

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def whatsapp_api_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.whatsapp_api_version}"
            f"/{self.whatsapp_phone_number_id}/messages"
        )

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set.")
        # Ensure async driver is used
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def validate_elisa2_path(self) -> "Settings":
        path = self.elisa2_root
        if not path.exists():
            raise ValueError(
                f"elisa2 root not found at '{path}'. "
                "Set ELISA2_PATH in .env to the absolute path of the elisa2/ directory."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton — import and call this everywhere."""
    return Settings()