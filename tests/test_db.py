import os
from uuid import uuid4

import numpy as np
import pytest

from docmind_service.chunking import chunk_pages
from docmind_service.db import load_dotenv, make_pool, migrate, migration_status
from docmind_service.embedding import HashingEmbedder
from docmind_service.store import PgStore


@pytest.fixture(scope="module")
def dsn():
    value = os.environ.get("DOCMIND_TEST_DATABASE_URL")
    if not value:
        pytest.skip("DOCMIND_TEST_DATABASE_URL is not set")
    if not value.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        pytest.fail("DOCMIND_TEST_DATABASE_URL must name a database ending in _test")
    migrate(value)
    return value


@pytest.fixture
def store(dsn):
    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        yield PgStore(pool, HashingEmbedder())
    finally:
        pool.close()


def add(store, tenant, *, sha=None, text="self attention is useful"):
    chunks = chunk_pages([text])
    embeddings = HashingEmbedder().embed_passages([chunk.text for chunk in chunks])
    return store.add_document(
        tenant_id=tenant,
        sha256=sha or ("a" * 64),
        filename="paper.pdf",
        pages=1,
        chunks=chunks,
        embeddings=embeddings,
    )


@pytest.mark.integration
def test_migrations_are_idempotent_and_report_the_version(dsn):
    assert "001_init" in migration_status(dsn)
    assert "003_tenancy_cache_logs" in migration_status(dsn)
    assert migrate(dsn) == []


@pytest.mark.integration
def test_store_roundtrip_is_idempotent_and_tenant_scoped(store):
    tenant_a, tenant_b = uuid4().hex, uuid4().hex
    record, created = add(store, tenant_a)
    assert created is True
    assert record.chunk_count == 1

    again, created_again = add(store, tenant_a)
    assert created_again is False
    assert again.document_id == record.document_id

    other, created_other = add(store, tenant_b)
    assert created_other is True
    assert other.document_id != record.document_id

    assert [item.document_id for item in store.list_documents(tenant_id=tenant_a)] == [
        record.document_id
    ]
    assert [item.document_id for item in store.list_documents(tenant_id=tenant_b)] == [
        other.document_id
    ]

    hits = store.retrieve(
        "attention",
        tenant_id=tenant_a,
        document_ids=None,
        top_k=5,
    )
    assert [hit.text for hit in hits] == ["self attention is useful"]


@pytest.mark.integration
def test_retrieval_can_be_restricted_to_one_document_and_delete_cascades(store):
    tenant = uuid4().hex
    first, _ = add(store, tenant, sha="b" * 64, text="self attention")
    second, _ = add(store, tenant, sha="c" * 64, text="banana bread")
    hits = store.retrieve(
        "attention",
        tenant_id=tenant,
        document_ids=[first.document_id],
        top_k=10,
    )
    assert [hit.document_id for hit in hits] == [first.document_id]

    assert store.delete_document(tenant_id=tenant, document_id=first.document_id) is True
    assert store.delete_document(tenant_id=tenant, document_id=first.document_id) is False
    hits = store.retrieve("attention", tenant_id=tenant, document_ids=None, top_k=10)
    assert [hit.document_id for hit in hits] == [second.document_id]


@pytest.mark.integration
def test_embedding_dimension_and_shape_validation(store):
    assert store.embedding_dimension() == 384
    chunks = chunk_pages(["too short"])
    with pytest.raises(ValueError):
        store.add_document(
            tenant_id=uuid4().hex,
            sha256="d" * 64,
            filename="x.pdf",
            pages=1,
            chunks=chunks,
            embeddings=np.zeros((len(chunks), 3), dtype=np.float32),
        )


@pytest.mark.integration
def test_query_through_pg_store(store, make_client):
    from docmind_service.fakes import ScriptedLLM

    add(store, "public", sha="e" * 64, text="self attention is useful")
    client = make_client(store=store, embedder=store.embedder, llm=ScriptedLLM(["Grounded [c1]."]))
    response = client.post("/v1/query", json={"question": "attention"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Grounded [c1]."
    assert len(body["citations"]) == 1
    assert body["citations"][0]["chunk_id"].endswith(":0")


@pytest.mark.integration
def test_upload_list_delete_through_the_api(store, make_client):
    from docmind_service.auth import InMemoryAuthStore
    from docmind_service.embedding import HashingEmbedder
    from docmind_service.fakes import ScriptedLLM
    from scripts.make_tiny_pdf import make_pdf

    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id="t1", scopes=["read", "write"])
    headers = {"X-API-Key": key}
    text = f"unique {uuid4().hex} " + "This page has enough extracted text to pass. " * 4
    data = make_pdf([text])
    client = make_client(
        store=store,
        embedder=HashingEmbedder(),
        llm=ScriptedLLM([]),
        auth_store=auth,
    )
    first = client.post(
        "/v1/documents",
        files={"file": ("paper.pdf", data, "application/pdf")},
        headers=headers,
    )
    assert first.status_code == 201
    document_id = first.json()["document_id"]
    second = client.post(
        "/v1/documents",
        files={"file": ("paper.pdf", data, "application/pdf")},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["document_id"] == document_id
    assert document_id in {
        item["document_id"] for item in client.get("/v1/documents", headers=headers).json()["items"]
    }
    assert client.delete(f"/v1/documents/{document_id}", headers=headers).status_code == 204


@pytest.mark.integration
def test_corpus_version_changes_on_add_and_delete(store):
    tenant = f"v-{uuid4().hex}"
    assert store.get_corpus_version(tenant) == "0"
    first, _ = add(store, tenant, sha="1" * 64)
    version_after_add = store.get_corpus_version(tenant)
    assert version_after_add != "0"
    _, created = add(store, tenant, sha="1" * 64)
    assert created is False
    assert store.get_corpus_version(tenant) == version_after_add
    assert store.delete_document(tenant_id=tenant, document_id=first.document_id) is True
    assert store.get_corpus_version(tenant) != version_after_add
    version_after_delete = store.get_corpus_version(tenant)
    assert store.delete_document(tenant_id=tenant, document_id=first.document_id) is False
    assert store.get_corpus_version(tenant) == version_after_delete


@pytest.mark.integration
def test_daily_cap_sql_counter(dsn):
    from docmind_service.ratelimit import DailyCap

    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        cap = DailyCap(pool, limit=10)
        scope = f"test-{uuid4().hex}"
        assert cap.increment(scope) == 1
        assert cap.increment(scope) == 2
    finally:
        pool.close()


def test_dotenv_loader_sets_missing_values_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMIND_DOTENV_KEEP", "original")
    monkeypatch.delenv("DOCMIND_DOTENV_NEW", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nDOCMIND_DOTENV_KEEP=replaced\nDOCMIND_DOTENV_NEW='new value'\n",
        encoding="utf-8",
    )
    load_dotenv(env)
    assert os.environ["DOCMIND_DOTENV_KEEP"] == "original"
    assert os.environ["DOCMIND_DOTENV_NEW"] == "new value"
