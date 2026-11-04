from dataclasses import dataclass
from uuid import UUID

from docmind_service.domain import LLMClient, LLMResult, RetrievedChunk, Retriever
from docmind_service.guardrails import (
    PROMPT_VERSION,
    build_prompt_v2,
    parse_citations,
    validate_output,
)

__all__ = [
    "MIN_EVIDENCE_SCORE",
    "NO_EVIDENCE_ANSWER",
    "PROMPT_TEMPLATE",
    "PROMPT_VERSION",
    "PROMPT_VERSION_V1",
    "QueryResult",
    "answer_question",
    "build_prompt",
    "parse_citations",
]

PROMPT_VERSION_V1 = "p7-v1"
NO_EVIDENCE_ANSWER = "I could not find relevant information in the indexed documents."
# The off arm (M3 behavior) keeps this fixed threshold; M6 makes the on arm measured.
MIN_EVIDENCE_SCORE = 0.2

PROMPT_TEMPLATE = """Answer the question using only the context below. If the context does not \
contain the answer, say so clearly.
Cite the chunks you used by their ids in square brackets, for example [c3].

Context:
{context}

Question: {question}

Answer:"""


@dataclass(frozen=True)
class QueryResult:
    answer: str
    citations: list[RetrievedChunk]
    refused: bool
    refusal_reason: str | None
    llm: LLMResult | None
    invalid_citations: int
    n_chunks: int


def build_prompt(
    question: str, chunks: list[RetrievedChunk]
) -> tuple[str, dict[str, RetrievedChunk]]:
    """Render the M3 prompt and the map from short ids (c1, c2, ...) to chunks."""
    mapping = {f"c{i}": chunk for i, chunk in enumerate(chunks, start=1)}
    blocks = [f"[{short}] (page {chunk.page})\n{chunk.text}" for short, chunk in mapping.items()]
    prompt = PROMPT_TEMPLATE.format(context="\n\n".join(blocks), question=question)
    return prompt, mapping


def answer_question(
    question: str,
    *,
    tenant_id: str = "public",
    retriever: Retriever,
    llm: LLMClient,
    document_ids: list[UUID] | None,
    top_k: int,
    query_vector=None,
    guardrails_enabled: bool = False,
    evidence_min_score: float = MIN_EVIDENCE_SCORE,
    canary: str | None = None,
    require_citation: bool = True,
    max_answer_chars: int = 4000,
) -> QueryResult:
    extra = {"query_vector": query_vector} if query_vector is not None else {}
    chunks = retriever.retrieve(
        question, tenant_id=tenant_id, document_ids=document_ids, top_k=top_k, **extra
    )
    if guardrails_enabled:
        chunks = [chunk for chunk in chunks if chunk.score >= evidence_min_score]
        if not chunks:
            return QueryResult(NO_EVIDENCE_ANSWER, [], True, "low_evidence", None, 0, 0)
        prompt, mapping = build_prompt_v2(question, chunks, canary or "")
        result = llm.complete(prompt)
        answer, cited, refused, reason, invalid = validate_output(
            result.text,
            mapping,
            canary=canary,
            require_citation=require_citation,
            chunk_texts=[chunk.text for chunk in chunks],
            max_answer_chars=max_answer_chars,
        )
        return QueryResult(answer, cited, refused, reason, result, invalid, len(chunks))

    chunks = [chunk for chunk in chunks if chunk.score >= MIN_EVIDENCE_SCORE]
    if not chunks:
        return QueryResult(NO_EVIDENCE_ANSWER, [], True, "no_evidence", None, 0, 0)
    prompt, mapping = build_prompt(question, chunks)
    result = llm.complete(prompt)
    cited, invalid = parse_citations(result.text, mapping)
    return QueryResult(result.text, cited, False, None, result, invalid, len(chunks))
