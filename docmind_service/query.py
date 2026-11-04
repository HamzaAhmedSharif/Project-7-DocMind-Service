import re
from dataclasses import dataclass
from uuid import UUID

from docmind_service.domain import LLMClient, LLMResult, RetrievedChunk, Retriever

PROMPT_VERSION = "p7-v1"
NO_EVIDENCE_ANSWER = "I could not find relevant information in the indexed documents."
# M6 makes this a measured setting; M5 needs nonsense questions to refuse.
MIN_EVIDENCE_SCORE = 0.2
_CITATION = re.compile(r"[\[【](c\d+)[\]】]")

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
    """Render the prompt and the map from short ids (c1, c2, ...) to chunks."""
    mapping = {f"c{i}": chunk for i, chunk in enumerate(chunks, start=1)}
    blocks = [f"[{short}] (page {chunk.page})\n{chunk.text}" for short, chunk in mapping.items()]
    prompt = PROMPT_TEMPLATE.format(context="\n\n".join(blocks), question=question)
    return prompt, mapping


def parse_citations(
    answer: str, mapping: dict[str, RetrievedChunk]
) -> tuple[list[RetrievedChunk], int]:
    """Chunks cited in the answer, in order of first appearance, and the count of unknown ids."""
    cited: list[RetrievedChunk] = []
    seen: set[str] = set()
    invalid = 0
    for short in _CITATION.findall(answer):
        if short in seen:
            continue
        seen.add(short)
        if short in mapping:
            cited.append(mapping[short])
        else:
            invalid += 1
    return cited, invalid


def answer_question(
    question: str,
    *,
    tenant_id: str = "public",
    retriever: Retriever,
    llm: LLMClient,
    document_ids: list[UUID] | None,
    top_k: int,
) -> QueryResult:
    chunks = retriever.retrieve(
        question, tenant_id=tenant_id, document_ids=document_ids, top_k=top_k
    )
    chunks = [chunk for chunk in chunks if chunk.score >= MIN_EVIDENCE_SCORE]
    if not chunks:
        return QueryResult(NO_EVIDENCE_ANSWER, [], True, "no_evidence", None, 0, 0)
    prompt, mapping = build_prompt(question, chunks)
    result = llm.complete(prompt)
    cited, invalid = parse_citations(result.text, mapping)
    return QueryResult(result.text, cited, False, None, result, invalid, len(chunks))
