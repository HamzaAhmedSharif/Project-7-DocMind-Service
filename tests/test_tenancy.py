from docmind_service.auth import InMemoryAuthStore
from docmind_service.config import Settings
from docmind_service.domain import RetrievedChunk
from docmind_service.embedding import HashingEmbedder
from docmind_service.fakes import FakeLLM, InMemoryDocumentStore, InMemoryRetriever, ScriptedLLM
from scripts.make_tiny_pdf import make_pdf

LONG = "This page has enough extracted text to pass the extraction check. " * 4


class ScopedRetriever:
    """Returns one chunk per document the tenant actually owns."""

    def __init__(self, store):
        self.store = store

    def retrieve(self, question, *, tenant_id, document_ids, top_k, query_vector=None):
        records = self.store.list_documents(tenant_id=tenant_id)
        if document_ids:
            wanted = {str(item) for item in document_ids}
            records = [record for record in records if str(record.document_id) in wanted]
        return [
            RetrievedChunk(
                chunk_id=f"{record.document_id}:0",
                document_id=record.document_id,
                page=1,
                text=f"unique-{record.tenant_id}-{record.document_id} " + LONG,
                score=1.0,
            )
            for record in records[:top_k]
        ]


def keyed_app(make_client, *, tenants, settings=None, llm=None, retriever=None):
    store = InMemoryDocumentStore()
    auth = InMemoryAuthStore()
    headers = {}
    for tenant in tenants:
        _, key = auth.create(tenant_id=tenant, scopes=["read", "write"])
        headers[tenant] = {"X-API-Key": key}
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        auth_store=auth,
        settings=settings,
        llm=llm or FakeLLM(),
        retriever=retriever or ScopedRetriever(store),
    )
    return client, headers, store


def upload(client, headers, name="paper.pdf", pages=None):
    data = make_pdf(pages or [LONG])
    return client.post(
        "/v1/documents",
        files={"file": (name, data, "application/pdf")},
        headers=headers,
    )


def test_tenant_isolation_matrix(make_client):
    client, headers, _ = keyed_app(make_client, tenants=["alpha", "beta"])
    alpha = upload(client, headers["alpha"], name="alpha.pdf")
    beta = upload(client, headers["beta"], name="beta.pdf")
    assert alpha.status_code == 201
    assert beta.status_code == 201
    alpha_id = alpha.json()["document_id"]
    beta_id = beta.json()["document_id"]
    assert alpha_id != beta_id

    alpha_list = client.get("/v1/documents", headers=headers["alpha"]).json()["items"]
    beta_list = client.get("/v1/documents", headers=headers["beta"]).json()["items"]
    assert [item["document_id"] for item in alpha_list] == [alpha_id]
    assert [item["document_id"] for item in beta_list] == [beta_id]

    foreign_delete = client.delete(f"/v1/documents/{alpha_id}", headers=headers["beta"])
    assert foreign_delete.status_code == 404
    assert [
        item["document_id"]
        for item in client.get("/v1/documents", headers=headers["alpha"]).json()["items"]
    ] == [alpha_id]

    own_query = client.post(
        "/v1/query",
        json={"question": "anything", "document_ids": [alpha_id]},
        headers=headers["alpha"],
    )
    assert own_query.status_code == 200
    assert own_query.json()["citations"][0]["document_id"] == alpha_id

    foreign_filter = client.post(
        "/v1/query",
        json={"question": "anything", "document_ids": [alpha_id]},
        headers=headers["beta"],
    )
    assert foreign_filter.status_code == 200
    assert foreign_filter.json()["refused"] is True
    assert foreign_filter.json()["citations"] == []


def test_the_same_file_uploaded_by_two_tenants_gets_two_documents(make_client):
    client, headers, _ = keyed_app(make_client, tenants=["alpha", "beta"])
    first = upload(client, headers["alpha"])
    second = upload(client, headers["beta"])
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["sha256"] == second.json()["sha256"]
    assert first.json()["document_id"] != second.json()["document_id"]


def test_document_quota_returns_403_quota_exceeded(make_client):
    store = InMemoryDocumentStore()
    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id="quota", scopes=["read", "write"], max_documents=1)
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        auth_store=auth,
        retriever=ScopedRetriever(store),
    )
    headers = {"X-API-Key": key}
    assert upload(client, headers, name="one.pdf").status_code == 201
    second = upload(client, headers, name="two.pdf", pages=[LONG + " second"])
    assert second.status_code == 403
    assert second.json()["code"] == "quota_exceeded"
    assert "1" in second.json()["detail"]


def test_page_quota_returns_403_quota_exceeded(make_client):
    store = InMemoryDocumentStore()
    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id="quota", scopes=["read", "write"], max_pages=1)
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        auth_store=auth,
        retriever=ScopedRetriever(store),
    )
    response = upload(client, {"X-API-Key": key}, pages=[LONG, LONG + " second"])
    assert response.status_code == 403
    assert response.json()["code"] == "quota_exceeded"
    assert "page" in response.json()["detail"]


def test_rate_limit_headers_and_429_for_a_key(make_client):
    client, headers, _ = keyed_app(
        make_client,
        tenants=["limited"],
        settings=Settings(_env_file=None, key_rpm=2),
    )
    first = client.post(
        "/v1/query",
        json={"question": "self attention"},
        headers=headers["limited"],
    )
    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    second = client.post(
        "/v1/query", json={"question": "self attention"}, headers=headers["limited"]
    )
    assert second.status_code == 200
    assert second.headers["x-ratelimit-remaining"] == "0"
    third = client.post(
        "/v1/query", json={"question": "self attention"}, headers=headers["limited"]
    )
    assert third.status_code == 429
    assert third.headers["x-ratelimit-limit"] == "2"
    assert third.headers["x-ratelimit-remaining"] == "0"
    assert int(third.headers["retry-after"]) >= 1


def test_anonymous_rate_limit_headers(make_client):
    client = make_client(settings=Settings(_env_file=None, demo_ip_per_min=2))
    first = client.post("/v1/query", json={"question": "self attention"})
    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    client.post("/v1/query", json={"question": "self attention"})
    third = client.post("/v1/query", json={"question": "self attention"})
    assert third.status_code == 429
    assert third.headers["x-ratelimit-remaining"] == "0"


def test_global_cap_is_shared_between_anonymous_and_keyed_callers(make_client):
    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id="keyed")
    client = make_client(
        settings=Settings(
            _env_file=None,
            global_daily_llm_cap=1,
            demo_daily_cap=10,
            key_daily_queries=10,
        ),
        auth_store=auth,
    )
    anonymous = client.post("/v1/query", json={"question": "self attention"})
    assert anonymous.status_code == 200
    keyed = client.post(
        "/v1/query",
        json={"question": "self attention"},
        headers={"X-API-Key": key},
    )
    assert keyed.status_code == 429
    assert keyed.json()["code"] == "daily_cap_reached"


def test_refusal_does_not_consume_the_cap(make_client):
    client = make_client(
        settings=Settings(_env_file=None, global_daily_llm_cap=1),
        llm=ScriptedLLM(["Grounded [c1]."]),
    )
    refused = client.post("/v1/query", json={"question": "zxqv zxqv zxqv"})
    assert refused.status_code == 200
    assert refused.json()["refused"] is True
    allowed = client.post("/v1/query", json={"question": "self attention"})
    assert allowed.status_code == 200
    assert allowed.json()["refused"] is False


def test_cache_hit_does_not_consume_the_cap(make_client):
    store = InMemoryDocumentStore()
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        settings=Settings(_env_file=None, global_daily_llm_cap=2, cache_threshold=0.999),
    )
    first = client.post("/v1/query", json={"question": "self attention"})
    assert first.status_code == 200
    assert first.json()["usage"]["cache"] == "miss"
    hit = client.post("/v1/query", json={"question": "self attention"})
    assert hit.status_code == 200
    assert hit.json()["usage"]["cache"] == "hit"
    assert hit.json()["usage"]["calls"] == 0
    second = client.post("/v1/query", json={"question": "multi head attention"})
    assert second.status_code == 200
    third = client.post("/v1/query", json={"question": "positional encoding"})
    assert third.status_code == 429


def test_cache_is_isolated_between_tenants(make_client):
    client, headers, _ = keyed_app(
        make_client,
        tenants=["alpha", "beta"],
        llm=ScriptedLLM(["alpha answer [c1].", "beta answer [c1]."]),
        retriever=InMemoryRetriever(),
    )
    first = client.post("/v1/query", json={"question": "self attention"}, headers=headers["alpha"])
    assert first.json()["answer"] == "alpha answer [c1]."
    assert first.json()["usage"]["cache"] == "miss"
    second = client.post("/v1/query", json={"question": "self attention"}, headers=headers["beta"])
    assert second.json()["answer"] == "beta answer [c1]."
    assert second.json()["usage"]["cache"] == "miss"


def test_upload_invalidates_the_cache(make_client):
    store = InMemoryDocumentStore()
    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id="t1", scopes=["read", "write"])
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        auth_store=auth,
        retriever=ScopedRetriever(store),
        settings=Settings(_env_file=None, cache_threshold=0.999),
    )
    headers = {"X-API-Key": key}
    assert upload(client, headers).status_code == 201
    first = client.post("/v1/query", json={"question": "anything"}, headers=headers)
    assert first.json()["usage"]["cache"] == "miss"
    assert upload(client, headers, name="second.pdf", pages=[LONG + " second"]).status_code == 201
    second = client.post("/v1/query", json={"question": "anything"}, headers=headers)
    assert second.json()["usage"]["cache"] == "miss"


def test_different_top_k_and_no_cache_bypass_the_cache(make_client):
    store = InMemoryDocumentStore()
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        settings=Settings(_env_file=None, cache_threshold=0.999),
    )
    first = client.post("/v1/query", json={"question": "self attention"})
    assert first.json()["usage"]["cache"] == "miss"
    different = client.post("/v1/query", json={"question": "self attention", "top_k": 3})
    assert different.json()["usage"]["cache"] == "miss"
    bypass = client.post(
        "/v1/query",
        json={"question": "self attention"},
        headers={"Cache-Control": "no-cache"},
    )
    assert bypass.json()["usage"]["cache"] == "bypass"


def test_query_vector_is_computed_once_per_request(make_client):
    class CountingEmbedder(HashingEmbedder):
        def __init__(self):
            super().__init__()
            self.queries = 0

        def embed_query(self, text):
            self.queries += 1
            return super().embed_query(text)

    embedder = CountingEmbedder()
    store = InMemoryDocumentStore()
    client = make_client(store=store, embedder=embedder)
    client.post("/v1/query", json={"question": "self attention"})
    assert embedder.queries == 1
