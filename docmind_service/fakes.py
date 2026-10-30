import re
from uuid import UUID

from docmind_service.domain import LLMResult, RetrievedChunk

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

    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else demo_chunks()

    def retrieve(
        self, question: str, *, document_ids: list[UUID] | None, top_k: int
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
        return scored[:top_k]


class FakeLLM:
    """Deterministic stand-in for a language model: cites the first context chunk."""

    def complete(self, prompt: str) -> LLMResult:
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
