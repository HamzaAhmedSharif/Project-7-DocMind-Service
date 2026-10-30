from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: UUID
    page: int
    text: str
    score: float


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
        self, question: str, *, document_ids: list[UUID] | None, top_k: int
    ) -> list[RetrievedChunk]: ...


class LLMClient(Protocol):
    def complete(self, prompt: str) -> LLMResult: ...


class ProviderError(Exception):
    """The language model provider failed or is unavailable."""


class RetrievalError(Exception):
    """The retrieval backend failed or is unavailable."""
