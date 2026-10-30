from uuid import uuid4

from docmind_service.domain import ProviderError, RetrievalError
from docmind_service.fakes import ScriptedLLM
from docmind_service.query import PROMPT_VERSION

QUESTION = {"question": "What is self-attention?"}


class BrokenRetriever:
    def __init__(self, error):
        self.error = error

    def retrieve(self, question, *, document_ids, top_k):
        raise self.error


class FalsyRetriever:
    """Has no content but must still be used instead of the demo retriever."""

    def __bool__(self):
        return False

    def retrieve(self, question, *, document_ids, top_k):
        return []


def test_query_returns_answer_citations_and_usage(make_client):
    llm = ScriptedLLM(["Grounded answer [c1]."])
    response = make_client(llm=llm).post("/v1/query", json=QUESTION)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Grounded answer [c1]."
    assert body["refused"] is False
    assert [c["chunk_id"] for c in body["citations"]] == ["demo:1"]
    assert body["citations"][0]["page"] == 1
    assert body["usage"]["calls"] == 1
    assert body["usage"]["cache"] == "bypass"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "What is self-attention?" in llm.prompts[0]


def test_query_refuses_without_calling_the_llm_when_nothing_matches(make_client):
    llm = ScriptedLLM([])
    response = make_client(llm=llm).post("/v1/query", json={"question": "zxqv"})
    body = response.json()
    assert response.status_code == 200
    assert body["refused"] is True
    assert body["refusal_reason"] == "no_evidence"
    assert body["citations"] == []
    assert body["usage"]["calls"] == 0
    assert llm.prompts == []


def test_query_respects_the_document_filter(make_client):
    llm = ScriptedLLM([])
    payload = {**QUESTION, "document_ids": [str(uuid4())]}
    response = make_client(llm=llm).post("/v1/query", json=payload)
    assert response.json()["refusal_reason"] == "no_evidence"
    assert llm.prompts == []


def test_multi_mode_is_not_implemented_yet(make_client):
    response = make_client().post("/v1/query", json={**QUESTION, "mode": "multi"})
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")


def test_provider_failure_returns_503_without_leaking_details(make_client):
    client = make_client(llm=ScriptedLLM([ProviderError("secret upstream detail")]))
    response = client.post("/v1/query", json=QUESTION)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["retry-after"] == "30"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "secret upstream detail" not in response.text


def test_retrieval_failure_returns_503(make_client):
    client = make_client(retriever=BrokenRetriever(RetrievalError("db down")))
    response = client.post("/v1/query", json=QUESTION)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert "db down" not in response.text


def test_unexpected_errors_return_a_500_problem_with_request_id(make_client):
    client = make_client(
        retriever=BrokenRetriever(RuntimeError("bug")), raise_server_exceptions=False
    )
    response = client.post("/v1/query", json=QUESTION)
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "bug" not in response.text


def test_validation_errors_carry_the_request_id(make_client):
    response = make_client().post("/v1/query", json={"question": ""})
    assert response.status_code == 422
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_top_k_above_the_limit_is_rejected(make_client):
    response = make_client().post("/v1/query", json={**QUESTION, "top_k": 21})
    assert response.status_code == 422


def test_a_falsy_retriever_is_still_used(make_client):
    response = make_client(retriever=FalsyRetriever()).post("/v1/query", json=QUESTION)
    assert response.status_code == 200
    assert response.json()["refusal_reason"] == "no_evidence"


def test_document_ids_must_have_between_1_and_100_entries(make_client):
    client = make_client()
    too_many = {**QUESTION, "document_ids": [str(uuid4()) for _ in range(101)]}
    empty = {**QUESTION, "document_ids": []}
    at_limit = {**QUESTION, "document_ids": [str(uuid4()) for _ in range(100)]}
    assert client.post("/v1/query", json=too_many).status_code == 422
    assert client.post("/v1/query", json=empty).status_code == 422
    assert client.post("/v1/query", json=at_limit).status_code == 200


def test_query_log_records_the_prompt_version(make_client, log_records):
    make_client().post("/v1/query", json=QUESTION)
    records = [r for r in log_records if r.name == "docmind.query"]
    assert len(records) == 1
    assert records[0].prompt_version == PROMPT_VERSION
