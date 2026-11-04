import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest

from docmind_service.auth import PgAuthStore
from docmind_service.cache import SemanticCache
from docmind_service.chunking import chunk_pages
from docmind_service.db import make_pool, migrate
from docmind_service.domain import QuotaExceeded
from docmind_service.embedding import HashingEmbedder
from docmind_service.querylog import QueryLogWriter
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
def pool(dsn):
    value = make_pool(dsn)
    value.open(wait=True)
    try:
        yield value
    finally:
        value.close()


def _embedding(text: str) -> np.ndarray:
    return HashingEmbedder().embed_query(text)


@pytest.mark.integration
def test_pg_auth_store_create_lookup_revoke_and_touch(pool):
    store = PgAuthStore(pool)
    tenant = f"auth-{uuid4().hex[:12]}"
    record, key = store.create(
        tenant_id=tenant,
        label="integration",
        scopes=["read", "write"],
        rpm=7,
        daily_queries=11,
        max_documents=2,
        max_pages=3,
    )
    assert key.startswith(f"dm_{record.prefix}_")
    assert len(record.key_hash) == 64
    assert record.tenant_id == tenant
    assert record.scopes == ("read", "write")

    looked_up = store.lookup(record.prefix)
    assert looked_up is not None
    assert looked_up.key_hash == record.key_hash
    assert looked_up.last_used_at is None

    store.touch(record.prefix)
    touched = store.lookup(record.prefix)
    assert touched.last_used_at is not None
    store.touch(record.prefix)
    assert store.lookup(record.prefix).last_used_at == touched.last_used_at

    assert record.prefix in {item.prefix for item in store.list()}
    assert store.revoke(record.prefix) is True
    assert store.revoke(record.prefix) is False
    assert store.lookup(record.prefix).revoked_at is not None


@pytest.mark.integration
def test_pg_auth_store_never_stores_the_full_key(pool):
    store = PgAuthStore(pool)
    record, key = store.create(
        tenant_id=f"auth-{uuid4().hex[:12]}",
        label="",
        scopes=["read"],
        rpm=None,
        daily_queries=None,
        max_documents=None,
        max_pages=None,
    )
    with pool.connection(timeout=3) as conn:
        row = conn.execute(
            "SELECT key_hash, prefix FROM api_keys WHERE prefix = %s", (record.prefix,)
        ).fetchone()
    assert row[0] == record.key_hash
    assert key not in row[0]
    assert key != row[1]


@pytest.mark.integration
def test_pg_cache_roundtrip_hits_tenant_and_corpus_isolation(pool):
    cache = SemanticCache(pool)
    tenant = f"cache-{uuid4().hex[:12]}"
    vector = _embedding("self attention")
    cache.store(
        tenant_id=tenant,
        corpus_version="v1",
        scope_hash="scope",
        embedding=vector,
        answer_json={"answer": "a"},
    )
    hit = cache.lookup(
        tenant_id=tenant,
        corpus_version="v1",
        scope_hash="scope",
        embedding=vector,
        threshold=0.9,
    )
    assert hit == {"answer": "a"}
    with pool.connection(timeout=3) as conn:
        hits = conn.execute(
            "SELECT hits FROM semantic_cache WHERE tenant_id = %s", (tenant,)
        ).fetchone()[0]
    assert hits == 1
    assert (
        cache.lookup(
            tenant_id=f"other-{uuid4().hex[:12]}",
            corpus_version="v1",
            scope_hash="scope",
            embedding=vector,
            threshold=0.9,
        )
        is None
    )
    assert (
        cache.lookup(
            tenant_id=tenant,
            corpus_version="v2",
            scope_hash="scope",
            embedding=vector,
            threshold=0.9,
        )
        is None
    )
    with pool.connection(timeout=3) as conn:
        conn.execute("DELETE FROM semantic_cache WHERE tenant_id = %s", (tenant,))


@pytest.mark.integration
def test_pg_cache_purges_old_corpus_versions_and_evicts(pool):
    cache = SemanticCache(pool, max_rows=2)
    tenant = f"cache-{uuid4().hex[:12]}"
    vector = _embedding("attention")
    for index in range(3):
        cache.store(
            tenant_id=tenant,
            corpus_version="v1",
            scope_hash=f"scope-{index}",
            embedding=vector,
            answer_json={"answer": str(index)},
        )
    with pool.connection(timeout=3) as conn:
        count = conn.execute(
            "SELECT count(*) FROM semantic_cache WHERE tenant_id = %s", (tenant,)
        ).fetchone()[0]
    assert count == 2
    assert cache.purge(tenant_id=tenant, corpus_version="v2") == 2
    with pool.connection(timeout=3) as conn:
        conn.execute("DELETE FROM semantic_cache WHERE tenant_id = %s", (tenant,))


@pytest.mark.integration
def test_pg_query_log_stores_redacted_text_and_no_keyed_rows(pool):
    writer = QueryLogWriter(pool=pool)
    request_id = f"req-{uuid4().hex}"
    email = f"unique-{uuid4().hex}@example.com"
    word = f"quantum{uuid4().hex[:10]}"
    writer.write(
        tenant_id="public",
        request_id=request_id,
        question=f"email {email} about {word}",
        n_chunks=1,
        refused=False,
        refusal_reason=None,
        prompt_tokens=10,
        completion_tokens=5,
        cache="miss",
        anonymous=True,
    )
    with pool.connection(timeout=3) as conn:
        row = conn.execute(
            "SELECT question_redacted FROM query_log WHERE request_id = %s", (request_id,)
        ).fetchone()
    assert row is not None
    assert email not in row[0]
    assert word in row[0]
    assert len(row[0]) <= 500

    keyed_request = f"req-{uuid4().hex}"
    writer.write(
        tenant_id="t1",
        request_id=keyed_request,
        question="anything",
        n_chunks=0,
        refused=False,
        refusal_reason=None,
        prompt_tokens=0,
        completion_tokens=0,
        cache="bypass",
        anonymous=False,
    )
    with pool.connection(timeout=3) as conn:
        count = conn.execute(
            "SELECT count(*) FROM query_log WHERE request_id = %s", (keyed_request,)
        ).fetchone()[0]
        conn.execute("DELETE FROM query_log WHERE request_id = %s", (request_id,))
    assert count == 0


@pytest.mark.integration
def test_pg_query_log_purge_old(pool):
    writer = QueryLogWriter(pool=pool)
    request_id = f"req-{uuid4().hex}"
    writer.write(
        tenant_id="public",
        request_id=request_id,
        question="old question",
        n_chunks=0,
        refused=False,
        refusal_reason=None,
        prompt_tokens=0,
        completion_tokens=0,
        cache="bypass",
        anonymous=True,
    )
    writer._clock = lambda: datetime.now(UTC) + timedelta(days=31)
    assert writer.purge_old() >= 1
    with pool.connection(timeout=3) as conn:
        count = conn.execute(
            "SELECT count(*) FROM query_log WHERE request_id = %s", (request_id,)
        ).fetchone()[0]
    assert count == 0


@pytest.mark.integration
def test_pg_store_quotas(pool):
    store = PgStore(pool, HashingEmbedder())
    tenant = f"quota-{uuid4().hex[:12]}"
    chunks = chunk_pages(["This page has enough extracted text to pass. " * 4])
    embeddings = HashingEmbedder().embed_passages([chunk.text for chunk in chunks])
    store.add_document(
        tenant_id=tenant,
        sha256="a" * 64,
        filename="one.pdf",
        pages=1,
        chunks=chunks,
        embeddings=embeddings,
        max_documents=1,
    )
    with pytest.raises(QuotaExceeded):
        store.add_document(
            tenant_id=tenant,
            sha256="b" * 64,
            filename="two.pdf",
            pages=1,
            chunks=chunks,
            embeddings=embeddings,
            max_documents=1,
        )
    with pytest.raises(QuotaExceeded):
        store.add_document(
            tenant_id=f"pages-{uuid4().hex[:12]}",
            sha256="c" * 64,
            filename="two-pages.pdf",
            pages=2,
            chunks=chunks,
            embeddings=embeddings,
            max_pages=1,
        )
    for record in store.list_documents(tenant_id=tenant):
        store.delete_document(tenant_id=tenant, document_id=record.document_id)
