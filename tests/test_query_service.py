from uuid import uuid4

from docmind_service.domain import RetrievedChunk
from docmind_service.fakes import ScriptedLLM
from docmind_service.query import (
    NO_EVIDENCE_ANSWER,
    answer_question,
    build_prompt,
    parse_citations,
)

DOC = uuid4()


def chunk(n: int, text: str = "some text", page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=f"x:{n}", document_id=DOC, page=page, text=text, score=1.0 / n)


class SpyRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def retrieve(self, question, *, document_ids, top_k):
        self.calls.append((question, document_ids, top_k))
        return self.chunks


def test_build_prompt_numbers_chunks_and_includes_the_question():
    prompt, mapping = build_prompt("Why?", [chunk(1, "alpha", page=3), chunk(2, "beta")])
    assert list(mapping) == ["c1", "c2"]
    assert "[c1] (page 3)\nalpha" in prompt
    assert "[c2] (page 1)\nbeta" in prompt
    assert prompt.rstrip().endswith("Question: Why?\n\nAnswer:")


def test_parse_citations_returns_cited_chunks_in_order_of_first_appearance():
    _, mapping = build_prompt("q", [chunk(1), chunk(2), chunk(3)])
    cited, invalid = parse_citations("See [c3] and then [c1].", mapping)
    assert [c.chunk_id for c in cited] == ["x:3", "x:1"]
    assert invalid == 0


def test_parse_citations_counts_unknown_ids_and_ignores_duplicates():
    _, mapping = build_prompt("q", [chunk(1)])
    cited, invalid = parse_citations("[c1] again [c1] and [c9]", mapping)
    assert [c.chunk_id for c in cited] == ["x:1"]
    assert invalid == 1


def test_answer_question_refuses_without_calling_the_llm_when_nothing_is_retrieved():
    llm = ScriptedLLM([])
    result = answer_question("q", retriever=SpyRetriever([]), llm=llm, document_ids=None, top_k=5)
    assert result.refused is True
    assert result.refusal_reason == "no_evidence"
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.llm is None
    assert llm.prompts == []


def test_answer_question_passes_top_k_and_document_ids_to_the_retriever():
    retriever = SpyRetriever([])
    ids = [uuid4()]
    answer_question("q", retriever=retriever, llm=ScriptedLLM([]), document_ids=ids, top_k=7)
    assert retriever.calls == [("q", ids, 7)]


def test_answer_question_returns_citations_and_usage():
    llm = ScriptedLLM(["Yes [c2]."])
    result = answer_question(
        "q", retriever=SpyRetriever([chunk(1), chunk(2)]), llm=llm, document_ids=None, top_k=2
    )
    assert result.refused is False
    assert [c.chunk_id for c in result.citations] == ["x:2"]
    assert result.n_chunks == 2
    assert result.invalid_citations == 0
    assert result.llm is not None
    assert result.llm.prompt_tokens > 0
