from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from DOCMIND_-prefixed environment variables and a local .env file."""

    model_config = SettingsConfigDict(env_prefix="DOCMIND_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    max_pages: int = Field(default=200, ge=1, le=1000)
    default_mode: Literal["single", "multi"] = "single"


@lru_cache
def get_settings() -> Settings:
    return Settings()
