import re
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from docmind_service.domain import DocumentRecord, LLMResult, QuotaExceeded, RetrievedChunk
from docmind_service.rerank import rerank_with_fallback

DEMO_DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000001")

_SAMPLE = [
    (
        1,
        "Self-attention lets every token in a sequence weigh every other token "
        "when it builds its own representation.",
    ),
    (
        1,
        "Positional encodings are added to the input embeddings so that a model "
        "without recurrence still knows the order of the tokens.",
    ),
    (
        2,
        "Multi-head attention runs several attention functions in parallel and "
        "concatenates their outputs, so each head can look at a different kind "
        "of relationship.",
    ),
    (
        3,
        "A retrieval step finds the passages most similar to a question and "
        "passes them to the language model as context.",
    ),
]

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def demo_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"demo:{i}",
            document_id=DEMO_DOCUMENT_ID,
            page=page,
            text=text,
            score=0.0,
        )
        for i, (page, text) in enumerate(_SAMPLE, start=1)
    ]


class InMemoryRetriever:
    """Deterministic keyword-overlap retriever for tests, demos and CI smoke tests."""

    def __init__(
        self,
        chunks: list[RetrievedChunk] | None = None,
        *,
        reranker=None,
        rerank_candidates: int = 25,
    ) -> None:
        self.chunks = chunks if chunks is not None else demo_chunks()
        self.reranker = reranker
        self.rerank_candidates = rerank_candidates

    def retrieve(
        self,
        question: str,
        *,
        tenant_id: str = "public",
        document_ids: list[UUID] | None,
        top_k: int,
        query_vector=None,
    ) -> list[RetrievedChunk]:
        wanted = tokens(question)
        if not wanted:
            return []
        scored = []
        for chunk in self.chunks:
            if document_ids is not None and chunk.document_id not in document_ids:
                continue
            overlap = len(wanted & tokens(chunk.text))
            if overlap:
                scored.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        page=chunk.page,
                        text=chunk.text,
                        score=overlap / len(wanted),
                    )
                )
        scored.sort(key=lambda c: (-c.score, c.chunk_id))
        if self.reranker is None:
            return scored[:top_k]
        candidates = scored[: max(top_k, self.rerank_candidates)]
        return rerank_with_fallback(self.reranker, question, candidates)[:top_k]


class InMemoryDocumentStore:
    """DocumentStore double for API tests; no database or embeddings required."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], DocumentRecord] = {}
        self.corpus_versions: dict[str, str] = {}

    def ping(self) -> None:
        return None

    def embedding_dimension(self) -> int:
        return 384

    def add_document(
        self,
        *,
        tenant_id,
        sha256,
        filename,
        pages,
        chunks,
        embeddings,
        max_documents=None,
        max_pages=None,
    ) -> tuple[DocumentRecord, bool]:
        key = (tenant_id, sha256)
        existing = self.records.get(key)
        if existing is not None:
            return existing, False
        if max_documents is not None or max_pages is not None:
            mine = [record for (tenant, _), record in self.records.items() if tenant == tenant_id]
            if max_documents is not None and len(mine) >= max_documents:
                raise QuotaExceeded(
                    f"This tenant already has {len(mine)} of {max_documents} documents."
                )
            if max_pages is not None and sum(r.pages for r in mine) + pages > max_pages:
                raise QuotaExceeded(f"This upload would exceed the {max_pages}-page tenant limit.")
        record = DocumentRecord(
            document_id=uuid4(),
            tenant_id=tenant_id,
            sha256=sha256,
            filename=filename,
            pages=pages,
            chunk_count=len(chunks),
            created_at=datetime.now(UTC),
        )
        self.records[key] = record
        self.corpus_versions[tenant_id] = secrets.token_hex(8)
        return record, True

    def get_corpus_version(self, tenant_id: str) -> str:
        return self.corpus_versions.get(tenant_id, "0")

    def list_documents(self, *, tenant_id: str) -> list[DocumentRecord]:
        return [record for (tenant, _), record in self.records.items() if tenant == tenant_id]

    def delete_document(self, *, tenant_id: str, document_id: UUID) -> bool:
        for key, record in list(self.records.items()):
            if key[0] == tenant_id and record.document_id == document_id:
                del self.records[key]
                self.corpus_versions[tenant_id] = secrets.token_hex(8)
                return True
        return False


class FakeLLM:
    """Deterministic stand-in for a language model: cites the first context chunk."""

    def complete(self, prompt: str) -> LLMResult:
        delimiter = re.search(r"<<<c(\d+)", prompt)
        if delimiter:
            cited = f" [c{delimiter.group(1)}]"
        else:
            match = re.search(r"\[(c\d+)\]", prompt.split("Context:", 1)[-1])
            cited = f" [{match.group(1)}]" if match else ""
        text = f"Based on the provided context{cited}, here is a short grounded answer."
        return LLMResult(
            text=text,
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(text) // 4),
        )


class ScriptedLLM:
    """Returns scripted replies in order and records every prompt; used by tests."""

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> LLMResult:
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResult(
            text=reply,
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(reply) // 4),
        )
