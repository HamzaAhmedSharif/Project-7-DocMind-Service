from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC 9457 problem details. Every error response uses this shape."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyOut(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, str]


class DocumentOut(BaseModel):
    document_id: UUID
    sha256: str = Field(min_length=64, max_length=64)
    filename: str
    pages: int = Field(ge=1)
    chunks: int = Field(ge=0)
    created_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentOut]


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)] | None = None
    mode: Literal["single", "multi"] = "single"
    top_k: int | None = Field(default=None, ge=1, le=20)


class Citation(BaseModel):
    document_id: UUID
    page: int = Field(ge=1)
    chunk_id: str
    score: float


class Usage(BaseModel):
    calls: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    api_seconds: float = Field(ge=0)
    wait_seconds: float = Field(ge=0)
    cache: Literal["hit", "miss", "bypass"]


class QueryOut(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    refusal_reason: str | None = None
    usage: Usage
    request_id: str
