from dataclasses import dataclass
from uuid import UUID

from docmind_service.domain import LLMClient, LLMResult, RetrievedChunk, Retriever
from docmind_service.guardrails import (
    PROMPT_VERSION,
    build_prompt_v3,
    parse_citations,
    validate_output,
)
from docmind_service.metrics import RETRIEVAL, timer

__all__ = [
    "CITATION_REPAIR_SUFFIX",
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

# Appended to the prompt for the single citation-repair retry (P7.1; made
# quote-anchored in P7.2): the first answer carried no valid citation, so the
# model is told to answer again from the numbered chunks only, quoting the
# exact lines it relies on before answering from those quotes. P7.1's plainer
# suffix fired and still failed on d09/d11 in run B2; the quote-first form is
# the P7.2 hypothesis for the validator-lost facts.
CITATION_REPAIR_SUFFIX = (
    "\n\nYour previous answer did not cite the context chunks. Answer the question "
    "again using only the chunks above. First quote verbatim the exact lines from "
    "the chunks you will rely on, putting each quote in quotation marks followed "
    'by its chunk id in square brackets, for example "..." [c3]. Then write '
    "your answer using only those quoted lines, citing the same chunk ids. If the "
    "chunks do not contain the answer, say so clearly."
)

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
    with timer(RETRIEVAL):
        chunks = retriever.retrieve(
            question, tenant_id=tenant_id, document_ids=document_ids, top_k=top_k, **extra
        )
    if guardrails_enabled:
        # M6.4 evidence gate: a top-1 test only. If the best retrieved score
        # clears the threshold, every retrieved chunk goes into the prompt;
        # chunks are never filtered one by one. (P7.1 conformance fix: the
        # code previously filtered per chunk, silently dropping fact-bearing
        # chunks below the threshold from the prompt; see DECISIONS.)
        best_score = max((chunk.score for chunk in chunks), default=None)
        if best_score is None or best_score < evidence_min_score:
            return QueryResult(NO_EVIDENCE_ANSWER, [], True, "low_evidence", None, 0, 0)
        prompt, mapping = build_prompt_v3(question, chunks, canary or "")
        result = llm.complete(prompt)
        answer, cited, refused, reason, invalid = validate_output(
            result.text,
            mapping,
            canary=canary,
            require_citation=require_citation,
            chunk_texts=[chunk.text for chunk in chunks],
            max_answer_chars=max_answer_chars,
        )
        if refused and reason == "ungrounded":
            # Citation repair (P7.1): the answer carried no valid citation.
            # Retry once with an explicit cite-the-chunks instruction; refuse
            # only if the retry also has none. No other refusal kind
            # (low_evidence, output_blocked) is retried. The merged result
            # sums both calls: usage in the response is what the caps audit
            # and the evaluation count, so a repaired query must report the
            # attempts and tokens of the first call as well as the retry's.
            first = result
            result = llm.complete(prompt + CITATION_REPAIR_SUFFIX)
            result = LLMResult(
                text=result.text,
                calls=first.calls + result.calls,
                prompt_tokens=first.prompt_tokens + result.prompt_tokens,
                completion_tokens=first.completion_tokens + result.completion_tokens,
                api_seconds=first.api_seconds + result.api_seconds,
                wait_seconds=first.wait_seconds + result.wait_seconds,
            )
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
