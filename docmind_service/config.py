import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from DOCMIND_-prefixed environment variables and a local .env file."""

    model_config = SettingsConfigDict(env_prefix="DOCMIND_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    default_top_k: int = Field(default=10, ge=1, le=20)
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
    reranker_enabled: bool = True
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = Field(default=25, ge=1, le=100)
    git_sha: str | None = None
    uploads_enabled: bool = True
    demo_daily_cap: int = 300
    demo_ip_per_min: int = 5
    trust_proxy_hops: int = 0

    auth_cache_seconds: int = Field(default=60, ge=0)
    key_rpm: int = Field(default=30, ge=1)
    key_daily_queries: int = Field(default=200, ge=1)
    key_max_documents: int = Field(default=20, ge=1)
    key_max_pages: int = Field(default=500, ge=1)
    global_daily_llm_cap: int = Field(default=800, ge=1)
    metrics_token: SecretStr | None = None

    guardrails_enabled: bool = True
    require_citation: bool = True
    canary: str | None = None
    max_answer_chars: int = Field(default=4000, ge=1)
    evidence_min_score: float = Field(default=0.2, ge=0.0, le=1.0)

    cache_enabled: bool = True
    cache_threshold: float = Field(default=0.86, ge=0.0, le=1.0)
    cache_ttl_days: int = Field(default=30, ge=1)
    query_log_days: int = Field(default=30, ge=1)

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
    def metrics_token_value(self) -> str | None:
        return self.metrics_token.get_secret_value() if self.metrics_token else None

    @field_validator("git_sha", "metrics_token", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def commit_sha(self) -> str | None:
        # RENDER_GIT_COMMIT is set by some hosts; the image bakes DOCMIND_GIT_SHA.
        return self.git_sha or os.environ.get("RENDER_GIT_COMMIT") or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
