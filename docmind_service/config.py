import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from DOCMIND_-prefixed environment variables and a local .env file."""

    model_config = SettingsConfigDict(env_prefix="DOCMIND_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    default_top_k: int = Field(default=4, ge=1, le=20)
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    max_pages: int = Field(default=200, ge=1, le=1000)
    default_mode: Literal["single", "multi"] = "single"

    database_url: SecretStr | None = None
    database_url_direct: SecretStr | None = None
    auto_migrate: bool = False

    llm_provider: Literal["fake", "hosted"] = "fake"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_api_key: SecretStr | None = None
    llm_reasoning_effort: str = "low"
    llm_max_completion_tokens: int = Field(default=1024, ge=1)
    llm_max_wait_seconds: int = Field(default=20, ge=0)
    hosted_rpm: int = Field(default=20, ge=1)
    hosted_tpm: int = Field(default=8000, ge=1)

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    model_cache_dir: str | None = None
    git_sha: str | None = None

    @property
    def database_url_value(self) -> str | None:
        return self.database_url.get_secret_value() if self.database_url else None

    @property
    def database_url_direct_value(self) -> str | None:
        return self.database_url_direct.get_secret_value() if self.database_url_direct else None

    @property
    def llm_api_key_value(self) -> str | None:
        return self.llm_api_key.get_secret_value() if self.llm_api_key else None

    @property
    def commit_sha(self) -> str | None:
        return self.git_sha or os.environ.get("RENDER_GIT_COMMIT") or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
