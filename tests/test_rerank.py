"""Cross-encoder reranking (P7.3): reorder, top_k, fallback, logging, settings,
cache-scope separation, readyz and the PgStore integration path."""

import logging
import os
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY, generate_latest

from docmind_service.cache import SemanticCache
from docmind_service.chunking import chunk_pages
from docmind_service.config import Settings
from docmind_service.db import make_pool, migrate
from docmind_service.domain import RetrievedChunk
from docmind_service.embedding import HashingEmbedder
from docmind_service.fakes import (
    DEMO_DOCUMENT_ID,
    InMemoryDocumentStore,
    InMemoryRetriever,
)
from docmind_service.rerank import (
    FakeReranker,
    NoopReranker,
    OnnxCrossEncoderReranker,
)
from docmind_service.store import PgStore


class ExplodingReranker:
    """Test double that always fails, for the fallback path."""

    name = "boom"

    def rerank(self, question, chunks):
        raise RuntimeError("boom")

    def warm_up(self):
        return None


def _scored_chunks() -> list[RetrievedChunk]:
    """Five chunks with a known dense order for 'alpha beta gamma'."""
    texts = ["alpha beta", "alpha", "alpha beta gamma", "beta", "gamma"]
    return [
        RetrievedChunk(
            chunk_id=f"test:{i}",
            document_id=DEMO_DOCUMENT_ID,
            page=1,
            text=text,
            score=0.0,
        )
        for i, text in enumerate(texts, start=1)
    ]


def _rerank_total(result: str) -> float:
    text = generate_latest(REGISTRY).decode("utf-8")
    for line in text.splitlines():
        if line.startswith(f'docmind_rerank_total{{result="{result}"}}'):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def _dense_order() -> list[RetrievedChunk]:
    return InMemoryRetriever(_scored_chunks()).retrieve(
        "alpha beta gamma", tenant_id="public", document_ids=None, top_k=5
    )


def test_noop_reranker_returns_input_order():
    chunks = _scored_chunks()
    assert NoopReranker().rerank("alpha beta gamma", chunks) == chunks


def test_fake_reranker_reverses_order():
    chunks = _scored_chunks()
    assert FakeReranker().rerank("alpha beta gamma", chunks) == list(reversed(chunks))


def test_inmemory_retriever_reranks_candidates_then_top_k():
    retriever = InMemoryRetriever(_scored_chunks(), reranker=FakeReranker(), rerank_candidates=4)
    hits = retriever.retrieve("alpha beta gamma", tenant_id="public", document_ids=None, top_k=2)
    # Dense top-4 is [test:3, test:1, test:2, test:4]; the fake reverses it.
    assert [chunk.chunk_id for chunk in hits] == ["test:4", "test:2"]
    dense_scores = {chunk.chunk_id: chunk.score for chunk in _dense_order()}
    assert [chunk.score for chunk in hits] == [dense_scores[chunk.chunk_id] for chunk in hits]


def test_inmemory_retriever_without_reranker_is_unchanged():
    hits = InMemoryRetriever(_scored_chunks()).retrieve(
        "alpha beta gamma", tenant_id="public", document_ids=None, top_k=2
    )
    assert [chunk.chunk_id for chunk in hits] == ["test:3", "test:1"]


def test_rerank_fallback_keeps_dense_order_and_counts_it():
    before = _rerank_total("fallback")
    retriever = InMemoryRetriever(_scored_chunks(), reranker=ExplodingReranker())
    hits = retriever.retrieve("alpha beta gamma", tenant_id="public", document_ids=None, top_k=2)
    assert [chunk.chunk_id for chunk in hits] == ["test:3", "test:1"]
    assert _rerank_total("fallback") == before + 1


def test_successful_rerank_counts_ok():
    before = _rerank_total("ok")
    retriever = InMemoryRetriever(_scored_chunks(), reranker=FakeReranker())
    retriever.retrieve("alpha beta gamma", tenant_id="public", document_ids=None, top_k=2)
    assert _rerank_total("ok") == before + 1


def test_single_candidate_skips_rerank():
    chunks = [
        RetrievedChunk(
            chunk_id="s:1",
            document_id=DEMO_DOCUMENT_ID,
            page=1,
            text="zebra stripes",
            score=0.0,
        ),
        RetrievedChunk(
            chunk_id="s:2",
            document_id=DEMO_DOCUMENT_ID,
            page=1,
            text="plain text",
            score=0.0,
        ),
    ]
    before = _rerank_total("ok") + _rerank_total("fallback")
    retriever = InMemoryRetriever(chunks, reranker=FakeReranker())
    hits = retriever.retrieve("zebra", tenant_id="public", document_ids=None, top_k=2)
    assert [chunk.chunk_id for chunk in hits] == ["s:1"]
    assert _rerank_total("ok") + _rerank_total("fallback") == before


def test_rerank_failure_logs_no_question_text(caplog):
    marker = "UNIQUE-LOG-MARKER-9f3a7c"
    chunks = [
        RetrievedChunk(
            chunk_id=f"m:{i}",
            document_id=DEMO_DOCUMENT_ID,
            page=1,
            text=f"question {marker} number {i}",
            score=0.0,
        )
        for i in (1, 2)
    ]
    retriever = InMemoryRetriever(chunks, reranker=ExplodingReranker())
    with caplog.at_level(logging.WARNING, logger="docmind_service.rerank"):
        retriever.retrieve(f"question {marker}", tenant_id="public", document_ids=None, top_k=2)
    assert marker not in caplog.text
    assert "RuntimeError" in caplog.text


def test_reranker_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.reranker_enabled is True
    assert settings.reranker_model == "Xenova/ms-marco-MiniLM-L-6-v2"
    assert settings.rerank_candidates == 25


def test_reranker_settings_from_environment(monkeypatch):
    monkeypatch.setenv("DOCMIND_RERANKER_ENABLED", "false")
    monkeypatch.setenv("DOCMIND_RERANKER_MODEL", "other-model")
    monkeypatch.setenv("DOCMIND_RERANK_CANDIDATES", "12")
    settings = Settings(_env_file=None)
    assert settings.reranker_enabled is False
    assert settings.reranker_model == "other-model"
    assert settings.rerank_candidates == 12


def test_cache_scope_separates_reranker_configs(make_client):
    store = InMemoryDocumentStore()
    cache = SemanticCache(pool=None)

    def client_for(model: str):
        return make_client(
            store=store,
            embedder=HashingEmbedder(),
            settings=Settings(_env_file=None, reranker_model=model),
            cache=cache,
        )

    first = client_for("model-a")
    second = client_for("model-b")
    third = client_for("model-a")
    question = {"question": "self attention"}
    assert first.post("/v1/query", json=question).json()["usage"]["cache"] == "miss"
    assert second.post("/v1/query", json=question).json()["usage"]["cache"] == "miss"
    assert third.post("/v1/query", json=question).json()["usage"]["cache"] == "hit"


def test_readyz_reports_reranker_ok(make_client):
    client = make_client(
        store=InMemoryDocumentStore(),
        retriever=InMemoryRetriever(reranker=FakeReranker()),
    )
    assert client.get("/readyz").json()["checks"]["reranker"] == "ok"


def test_readyz_reports_reranker_disabled_when_absent(make_client):
    client = make_client(
        store=InMemoryDocumentStore(),
        retriever=InMemoryRetriever(),
    )
    assert client.get("/readyz").json()["checks"]["reranker"] == "disabled"


def test_onnx_reranker_requires_a_cache_dir():
    with pytest.raises(ValueError, match="MODEL_CACHE_DIR"):
        OnnxCrossEncoderReranker("Xenova/ms-marco-MiniLM-L-6-v2", cache_dir=None)


def test_onnx_reranker_missing_model_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        OnnxCrossEncoderReranker("Xenova/ms-marco-MiniLM-L-6-v2", cache_dir=tmp_path)


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
def stores(dsn):
    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        yield (
            PgStore(pool, HashingEmbedder()),
            PgStore(pool, HashingEmbedder(), reranker=FakeReranker(), rerank_candidates=3),
        )
    finally:
        pool.close()


@pytest.mark.integration
def test_pgstore_retrieve_reranks_then_top_k(stores):
    dense_store, rerank_store = stores
    tenant = uuid4().hex
    for index, text in enumerate(["alpha beta", "alpha", "alpha beta gamma"]):
        chunks = chunk_pages([text])
        embeddings = HashingEmbedder().embed_passages([chunk.text for chunk in chunks])
        dense_store.add_document(
            tenant_id=tenant,
            sha256=("b" * 63) + str(index),
            filename=f"p{index}.pdf",
            pages=1,
            chunks=chunks,
            embeddings=embeddings,
        )
    question = "alpha beta gamma"
    dense = dense_store.retrieve(question, tenant_id=tenant, document_ids=None, top_k=3)
    reranked = rerank_store.retrieve(question, tenant_id=tenant, document_ids=None, top_k=2)
    expected = list(reversed(dense))[:2]
    assert [chunk.chunk_id for chunk in reranked] == [chunk.chunk_id for chunk in expected]
    assert [chunk.score for chunk in reranked] == [chunk.score for chunk in expected]
