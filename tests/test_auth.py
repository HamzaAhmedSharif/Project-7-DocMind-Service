import re
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from docmind_service.admin import BEGIN, END, _create_key
from docmind_service.auth import (
    AuthCache,
    InMemoryAuthStore,
    InvalidKey,
    generate_key,
    hash_key,
)
from docmind_service.config import Settings
from docmind_service.embedding import HashingEmbedder
from docmind_service.fakes import InMemoryDocumentStore
from docmind_service.main import create_app
from scripts.make_tiny_pdf import make_pdf

KEY_RE = re.compile(r"^dm_[0-9a-f]{8}_[A-Za-z0-9_-]{32}$")
LONG = "This page has enough extracted text to pass the check. " * 4


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 4, tzinfo=UTC)

    def __call__(self):
        return self.now


def test_key_shape_and_uniqueness():
    keys = [generate_key() for _ in range(50)]
    assert all(KEY_RE.match(full) for full, _, _ in keys)
    assert len({full for full, _, _ in keys}) == 50
    assert len({prefix for _, prefix, _ in keys}) == 50
    assert all(hash_key(full) == digest for full, _, digest in keys)


def test_store_keeps_only_the_hash():
    store = InMemoryAuthStore()
    record, full = store.create(tenant_id="t1", scopes=["read", "write"])
    assert record.key_hash == hash_key(full)
    assert full not in record.__dict__.values()


def test_anonymous_without_a_header():
    principal = AuthCache(InMemoryAuthStore()).resolve(None, Settings(_env_file=None))
    assert principal.anonymous is True
    assert principal.tenant_id == "public"
    assert principal.scopes == frozenset({"read"})


def test_valid_key_resolves_to_tenant_and_scopes():
    store = InMemoryAuthStore()
    _, full = store.create(tenant_id="acme", scopes=["read", "write"])
    principal = AuthCache(store).resolve(full, Settings(_env_file=None))
    assert principal.anonymous is False
    assert principal.tenant_id == "acme"
    assert principal.scopes == frozenset({"read", "write"})
    assert principal.key_prefix == full.split("_")[1]


def test_malformed_header_is_401(make_client):
    response = make_client().get("/v1/documents", headers={"X-API-Key": "nope"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'ApiKey realm="docmind"'


def test_unknown_key_is_401(make_client):
    response = make_client().get("/v1/documents", headers={"X-API-Key": "dm_deadbeef_" + "a" * 32})
    assert response.status_code == 401


def test_revoked_key_takes_effect_after_the_cache_window():
    clock = Clock()
    store = InMemoryAuthStore(clock=clock)
    _, full = store.create(tenant_id="t1")
    cache = AuthCache(store, ttl_seconds=60, clock=lambda: clock.now.timestamp())
    assert cache.resolve(full, Settings(_env_file=None)).tenant_id == "t1"
    store.revoke(full.split("_")[1])
    assert cache.resolve(full, Settings(_env_file=None)).tenant_id == "t1"
    clock.now += timedelta(seconds=61)
    with pytest.raises(InvalidKey):
        cache.resolve(full, Settings(_env_file=None))


def test_last_used_at_is_updated_at_most_once_per_five_minutes():
    clock = Clock()
    store = InMemoryAuthStore(clock=clock)
    record, full = store.create(tenant_id="t1")
    cache = AuthCache(store, ttl_seconds=0, clock=lambda: clock.now.timestamp())
    cache.resolve(full, Settings(_env_file=None))
    first = store.records[record.prefix].last_used_at
    assert first is not None
    clock.now += timedelta(seconds=60)
    cache.resolve(full, Settings(_env_file=None))
    assert store.records[record.prefix].last_used_at == first
    clock.now += timedelta(seconds=301)
    cache.resolve(full, Settings(_env_file=None))
    assert store.records[record.prefix].last_used_at > first


def _keyed_client(make_client, tenant="t1", scopes=("read", "write"), settings=None):
    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id=tenant, scopes=list(scopes))
    client = make_client(
        store=InMemoryDocumentStore(),
        embedder=HashingEmbedder(),
        auth_store=auth,
        settings=settings,
    )
    return client, {"X-API-Key": key}


def test_anonymous_upload_is_403(make_client):
    client = make_client(store=InMemoryDocumentStore(), embedder=HashingEmbedder())
    response = client.post(
        "/v1/documents", files={"file": ("x.pdf", make_pdf([LONG]), "application/pdf")}
    )
    assert response.status_code == 403


def test_read_only_key_cannot_upload(make_client):
    client, headers = _keyed_client(make_client, scopes=("read",))
    response = client.post(
        "/v1/documents",
        files={"file": ("x.pdf", make_pdf([LONG]), "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 403


def test_public_tenant_is_read_only(make_client):
    client, headers = _keyed_client(make_client, tenant="public")
    response = client.post(
        "/v1/documents",
        files={"file": ("x.pdf", make_pdf([LONG]), "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 403


def test_admin_cli_refuses_reserved_tenants(capsys):
    args = Namespace(
        tenant="public",
        label="x",
        write=False,
        rpm=None,
        daily=None,
        max_docs=None,
        max_pages=None,
    )
    assert _create_key(None, args) == 2
    assert "must not be public, eval or redteam" in capsys.readouterr().err


def test_admin_cli_prints_the_key_once_between_markers(capsys):
    store = InMemoryAuthStore()
    args = Namespace(
        tenant="acme",
        label="portfolio",
        write=True,
        rpm=10,
        daily=20,
        max_docs=2,
        max_pages=5,
    )
    assert _create_key(store, args) == 0
    out = capsys.readouterr().out
    assert BEGIN in out and END in out
    key = out.split(BEGIN)[1].split(END)[0].strip()
    assert KEY_RE.match(key)
    assert key not in [record.key_hash for record in store.records.values()]
    assert store.records[key.split("_")[1]].tenant_id == "acme"


def test_full_key_never_appears_in_responses_or_logs(make_client, log_records):
    client, headers = _keyed_client(make_client)
    key = headers["X-API-Key"]
    response = client.post(
        "/v1/query", json={"question": "What is self-attention?"}, headers=headers
    )
    assert response.status_code == 200
    assert key not in response.text
    for record in log_records:
        assert key not in record.getMessage()
        assert key not in str(record.__dict__)

    malformed = "dm_deadbeef_" + "z" * 32
    bad = make_client().get("/v1/documents", headers={"X-API-Key": malformed})
    assert bad.status_code == 401
    assert malformed not in bad.text


def test_key_prefix_is_logged_for_a_keyed_query(make_client, log_records):
    client, headers = _keyed_client(make_client)
    client.post("/v1/query", json={"question": "What is self-attention?"}, headers=headers)
    query_records = [record for record in log_records if record.name == "docmind.query"]
    assert query_records
    assert query_records[-1].key_prefix == headers["X-API-Key"].split("_")[1]
    assert query_records[-1].tenant_id == "t1"


def test_auth_cache_ttl_zero_always_looks_up():
    class CountingStore(InMemoryAuthStore):
        def __init__(self):
            super().__init__()
            self.lookups = 0

        def lookup(self, prefix):
            self.lookups += 1
            return super().lookup(prefix)

    store = CountingStore()
    _, full = store.create(tenant_id="t1")
    cache = AuthCache(store, ttl_seconds=0)
    cache.resolve(full, Settings(_env_file=None))
    cache.resolve(full, Settings(_env_file=None))
    assert store.lookups == 2


def test_settings_defaults_match_the_m6_contract():
    settings = Settings(_env_file=None)
    assert settings.auth_cache_seconds == 60
    assert settings.key_rpm == 30
    assert settings.key_daily_queries == 200
    assert settings.key_max_documents == 20
    assert settings.key_max_pages == 500
    assert settings.global_daily_llm_cap == 800
    assert settings.guardrails_enabled is True
    assert settings.max_answer_chars == 4000
    assert settings.query_log_days == 30


def test_create_app_wires_an_in_memory_auth_store():
    app = create_app(settings=Settings(_env_file=None))
    assert isinstance(app.state.auth_store, InMemoryAuthStore)
    assert TestClient(app).get("/healthz").status_code == 200
