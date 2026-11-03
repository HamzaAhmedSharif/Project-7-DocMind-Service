from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import numpy as np

if TYPE_CHECKING:
    from docmind_service.chunking import Chunk


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: UUID
    page: int
    text: str
    score: float


@dataclass(frozen=True)
class DocumentRecord:
    document_id: UUID
    tenant_id: str
    sha256: str
    filename: str
    pages: int
    chunk_count: int
    created_at: datetime


@dataclass(frozen=True)
class LLMResult:
    text: str
    calls: int = 1
    prompt_tokens: int = 0
    completion_tokens: int = 0
    api_seconds: float = 0.0
    wait_seconds: float = 0.0


class Retriever(Protocol):
    def retrieve(
        self,
        question: str,
        *,
        tenant_id: str,
        document_ids: list[UUID] | None,
        top_k: int,
    ) -> list[RetrievedChunk]: ...


class Embedder(Protocol):
    dim: int

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class DocumentStore(Protocol):
    def add_document(
        self,
        *,
        tenant_id: str,
        sha256: str,
        filename: str,
        pages: int,
        chunks: list["Chunk"],
        embeddings: np.ndarray,
    ) -> tuple[DocumentRecord, bool]: ...

    def list_documents(self, *, tenant_id: str) -> list[DocumentRecord]: ...

    def delete_document(self, *, tenant_id: str, document_id: UUID) -> bool: ...

    def ping(self) -> None: ...


class LLMClient(Protocol):
    def complete(self, prompt: str) -> LLMResult: ...


class ProviderError(Exception):
    """The language model provider failed or is unavailable."""

    def __init__(self, message: str = "", *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class RetrievalError(Exception):
    """The retrieval backend failed or is unavailable."""
