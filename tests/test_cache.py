from datetime import UTC, datetime, timedelta

import numpy as np

from docmind_service.cache import CacheRow, SemanticCache, scope_hash

BASE = dict(
    document_ids=None,
    top_k=5,
    mode="single",
    prompt_version="p7-v2",
    model_name="openai/gpt-oss-120b",
    guardrails_enabled=True,
    evidence_min_score=0.2,
    require_citation=True,
    reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
    rerank_candidates=25,
)


class Clock:
    def __init__(self, now=None):
        self.now = now or datetime(2026, 11, 4, tzinfo=UTC)

    def __call__(self):
        return self.now


def test_scope_hash_is_stable_and_changes_with_every_input():
    baseline = scope_hash(**BASE)
    assert scope_hash(**BASE) == baseline
    variants = [
        {**BASE, "document_ids": ["00000000-0000-4000-8000-000000000001"]},
        {**BASE, "top_k": 6},
        {**BASE, "mode": "multi"},
        {**BASE, "prompt_version": "p7-v1"},
        {**BASE, "model_name": "other-model"},
        {**BASE, "guardrails_enabled": False},
        {**BASE, "evidence_min_score": 0.3},
        {**BASE, "require_citation": False},
        {**BASE, "reranker_model": "other-model"},
        {**BASE, "rerank_candidates": 12},
        {**BASE, "reranker_model": None, "rerank_candidates": None},
    ]
    for variant in variants:
        assert scope_hash(**variant) != baseline


def test_scope_hash_sorts_document_ids():
    first = scope_hash(**{**BASE, "document_ids": ["b", "a"]})
    second = scope_hash(**{**BASE, "document_ids": ["a", "b"]})
    assert first == second


def test_lookup_is_a_miss_when_the_cache_is_empty():
    cache = SemanticCache(pool=None)
    assert (
        cache.lookup(
            tenant_id="t1",
            corpus_version="v1",
            scope_hash="s",
            embedding=np.array([1.0, 0.0]),
            threshold=0.9,
        )
        is None
    )


def test_store_then_lookup_is_a_hit_and_increments_hits():
    cache = SemanticCache(pool=None)
    cache.store(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.array([1.0, 0.0]),
        answer_json={"answer": "a"},
    )
    hit = cache.lookup(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.array([1.0, 0.0]),
        threshold=0.9,
    )
    assert hit == {"answer": "a"}
    assert cache.rows[0].hits == 1


def test_lookup_below_the_threshold_is_a_miss():
    cache = SemanticCache(pool=None)
    cache.store(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.array([1.0, 0.0]),
        answer_json={"answer": "a"},
    )
    assert (
        cache.lookup(
            tenant_id="t1",
            corpus_version="v1",
            scope_hash="s",
            embedding=np.array([0.0, 1.0]),
            threshold=0.9,
        )
        is None
    )


def test_lookup_requires_the_same_tenant_corpus_and_scope():
    cache = SemanticCache(pool=None)
    cache.store(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.array([1.0, 0.0]),
        answer_json={"answer": "a"},
    )
    for kwargs in [
        {"tenant_id": "t2", "corpus_version": "v1", "scope_hash": "s"},
        {"tenant_id": "t1", "corpus_version": "v2", "scope_hash": "s"},
        {"tenant_id": "t1", "corpus_version": "v1", "scope_hash": "other"},
    ]:
        assert cache.lookup(embedding=np.array([1.0, 0.0]), threshold=0.9, **kwargs) is None


def test_rows_expire_after_the_ttl():
    clock = Clock()
    cache = SemanticCache(pool=None, ttl_days=30, clock=clock)
    cache.store(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.array([1.0, 0.0]),
        answer_json={"answer": "a"},
    )
    clock.now += timedelta(days=31)
    assert (
        cache.lookup(
            tenant_id="t1",
            corpus_version="v1",
            scope_hash="s",
            embedding=np.array([1.0, 0.0]),
            threshold=0.9,
        )
        is None
    )


def test_eviction_keeps_at_most_500_rows_per_tenant():
    cache = SemanticCache(pool=None, max_rows=2)
    for index in range(3):
        cache.store(
            tenant_id="t1",
            corpus_version="v1",
            scope_hash=f"s{index}",
            embedding=np.array([1.0, 0.0]),
            answer_json={"answer": str(index)},
        )
    assert len([row for row in cache.rows if row.tenant_id == "t1"]) == 2
    assert {row.answer_json["answer"] for row in cache.rows} == {"1", "2"}


def test_purge_removes_old_rows_and_old_corpus_versions_for_one_tenant():
    clock = Clock()
    cache = SemanticCache(pool=None, ttl_days=30, clock=clock)
    for tenant, version in [("t1", "v1"), ("t1", "v2"), ("t2", "v1")]:
        cache.store(
            tenant_id=tenant,
            corpus_version=version,
            scope_hash="s",
            embedding=np.array([1.0, 0.0]),
            answer_json={"answer": tenant + version},
        )
    cache.purge(tenant_id="t1", corpus_version="v2")
    assert [row.answer_json["answer"] for row in cache.rows] == ["t1v2", "t2v1"]
    clock.now += timedelta(days=31)
    cache.purge()
    assert cache.rows == []


def test_maybe_purge_runs_at_most_once_an_hour():
    clock = Clock()
    cache = SemanticCache(pool=None, ttl_days=30, clock=clock)
    cache.maybe_purge(tenant_id="t1", corpus_version="v1")
    old = CacheRow(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.array([1.0, 0.0]),
        answer_json={},
        created_at=clock.now - timedelta(days=60),
    )
    cache.rows.append(old)
    cache.maybe_purge(tenant_id="t1", corpus_version="v1")
    assert old in cache.rows
    clock.now += timedelta(hours=1, seconds=1)
    cache.maybe_purge(tenant_id="t1", corpus_version="v1")
    assert old not in cache.rows


def test_zero_vector_does_not_divide_by_zero():
    cache = SemanticCache(pool=None)
    cache.store(
        tenant_id="t1",
        corpus_version="v1",
        scope_hash="s",
        embedding=np.zeros(2),
        answer_json={"answer": "a"},
    )
    assert (
        cache.lookup(
            tenant_id="t1",
            corpus_version="v1",
            scope_hash="s",
            embedding=np.zeros(2),
            threshold=0.1,
        )
        is None
    )


def test_refusals_are_not_stored_by_the_api(make_client):
    from docmind_service.embedding import HashingEmbedder
    from docmind_service.fakes import InMemoryDocumentStore

    client = make_client(
        store=InMemoryDocumentStore(),
        embedder=HashingEmbedder(),
        settings=None,
    )
    first = client.post("/v1/query", json={"question": "zxqv zxqv zxqv"})
    assert first.json()["refused"] is True
    assert first.json()["usage"]["cache"] == "miss"
    second = client.post("/v1/query", json={"question": "zxqv zxqv zxqv"})
    assert second.json()["usage"]["cache"] == "miss"


def test_cache_hit_gets_a_new_request_id(make_client):
    from docmind_service.embedding import HashingEmbedder
    from docmind_service.fakes import InMemoryDocumentStore

    client = make_client(
        store=InMemoryDocumentStore(),
        embedder=HashingEmbedder(),
        settings=None,
    )
    first = client.post("/v1/query", json={"question": "self attention"})
    second = client.post("/v1/query", json={"question": "self attention"})
    assert second.json()["usage"]["cache"] == "hit"
    assert first.json()["request_id"] != second.json()["request_id"]


def test_cache_hit_keeps_the_original_citations(make_client):
    from docmind_service.embedding import HashingEmbedder
    from docmind_service.fakes import InMemoryDocumentStore

    client = make_client(
        store=InMemoryDocumentStore(),
        embedder=HashingEmbedder(),
        settings=None,
    )
    first = client.post("/v1/query", json={"question": "self attention"})
    second = client.post("/v1/query", json={"question": "self attention"})
    assert first.json()["citations"] == second.json()["citations"]
    assert second.json()["answer"] == first.json()["answer"]


def test_cache_disabled_reports_bypass(make_client):
    from docmind_service.config import Settings
    from docmind_service.embedding import HashingEmbedder
    from docmind_service.fakes import InMemoryDocumentStore

    client = make_client(
        store=InMemoryDocumentStore(),
        embedder=HashingEmbedder(),
        settings=Settings(_env_file=None, cache_enabled=False),
    )
    response = client.post("/v1/query", json={"question": "self attention"})
    assert response.json()["usage"]["cache"] == "bypass"
