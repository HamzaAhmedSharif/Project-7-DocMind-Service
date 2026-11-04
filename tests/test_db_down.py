"""Drill-1 regression: database failures surface as RetrievalError.

M7.4 drill 1 found that a dead database made POST /v1/query return 500:
PgStore.retrieve already translated psycopg errors, but the semantic
cache and the corpus-version lookup did not, and the query route calls
them before its RetrievalError handling. These tests pin the contract:
every database touch on the query path raises RetrievalError, which the
app maps to a 503 problem with Retry-After.
"""

import psycopg
import pytest

from docmind_service.cache import SemanticCache
from docmind_service.domain import RetrievalError
from docmind_service.store import PgStore


class DeadPool:
    def connection(self, timeout=None):
        raise psycopg.OperationalError("connection refused")


class DeadEmbedder:
    dim = 384


def test_cache_lookup_raises_retrieval_error_when_db_down():
    cache = SemanticCache(pool=DeadPool())
    with pytest.raises(RetrievalError):
        cache.lookup(
            tenant_id="public",
            corpus_version="1",
            scope_hash="s",
            embedding=[0.0] * 384,
            threshold=0.5,
        )


def test_cache_purge_raises_retrieval_error_when_db_down():
    cache = SemanticCache(pool=DeadPool())
    with pytest.raises(RetrievalError):
        cache.purge(tenant_id="public", corpus_version="1")


def test_corpus_version_raises_retrieval_error_when_db_down():
    store = PgStore(DeadPool(), DeadEmbedder())
    with pytest.raises(RetrievalError):
        store.get_corpus_version("public")
