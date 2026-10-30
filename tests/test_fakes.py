from uuid import uuid4

from docmind_service.fakes import FakeLLM, InMemoryRetriever
from docmind_service.query import build_prompt


def test_retriever_ranks_by_overlap_and_is_deterministic():
    retriever = InMemoryRetriever()
    first = retriever.retrieve("self attention", document_ids=None, top_k=3)
    again = retriever.retrieve("self attention", document_ids=None, top_k=3)
    assert first == again
    assert first[0].chunk_id == "demo:1"
    assert first[0].score >= first[-1].score


def test_retriever_filters_by_document_id():
    result = InMemoryRetriever().retrieve("self attention", document_ids=[uuid4()], top_k=3)
    assert result == []


def test_retriever_respects_top_k():
    assert len(InMemoryRetriever().retrieve("attention", document_ids=None, top_k=1)) == 1


def test_fake_llm_cites_the_first_context_chunk():
    retriever = InMemoryRetriever()
    chunks = retriever.retrieve("self attention", document_ids=None, top_k=2)
    prompt, _ = build_prompt("self attention", chunks)
    result = FakeLLM().complete(prompt)
    assert "[c1]" in result.text
    assert result.calls == 1
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
