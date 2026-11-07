import re
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

from docmind_service.cache import SemanticCache
from docmind_service.config import Settings
from docmind_service.db import make_pool
from docmind_service.embedding import HashingEmbedder
from docmind_service.fakes import InMemoryDocumentStore, ScriptedLLM
from docmind_service.metrics import render_metrics

METRIC_NAMES = [
    "docmind_http_requests_total",
    "docmind_http_request_duration_seconds",
    "docmind_query_total",
    "docmind_llm_calls_total",
    "docmind_llm_tokens_total",
    "docmind_llm_wait_seconds",
    "docmind_llm_api_seconds",
    "docmind_llm_shed_total",
    "docmind_guardrail_total",
    "docmind_cache_total",
    "docmind_retrieval_seconds",
    "docmind_embed_seconds",
    "docmind_db_pool",
    "docmind_db_errors_total",
    "docmind_build_info",
]
QUESTION = {"question": "What is self-attention?"}


def sample(name, labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def scrape(client):
    return client.get("/metrics").text


def http_series(text):
    series = set()
    for line in text.splitlines():
        if line.startswith("docmind_http_requests_total{"):
            series.add(line[len("docmind_http_requests_total{") :].split("}", 1)[0])
    return series


def test_exposition_contains_every_metric_name(make_client):
    make_client().get("/healthz")
    text = render_metrics(None).decode()
    for name in METRIC_NAMES:
        assert name in text
    assert re.search(r"^docmind_http_request_duration_seconds_bucket\{", text, re.M)


def test_answered_query_moves_counters(make_client):
    client = make_client(llm=ScriptedLLM(["Grounded answer [c1]."]))
    before = sample("docmind_query_total", {"outcome": "answered", "principal": "anonymous"})
    calls_before = sample("docmind_llm_calls_total", {})
    tokens_before = sample("docmind_llm_tokens_total", {"kind": "prompt"})
    response = client.post("/v1/query", json=QUESTION)
    assert response.status_code == 200
    assert sample("docmind_query_total", {"outcome": "answered", "principal": "anonymous"}) == (
        before + 1
    )
    assert sample("docmind_llm_calls_total", {}) == calls_before + 1
    assert sample("docmind_llm_tokens_total", {"kind": "prompt"}) > tokens_before


def test_refused_low_evidence_moves_the_outcome_counter(make_client):
    client = make_client(llm=ScriptedLLM([]))
    before = sample(
        "docmind_query_total", {"outcome": "refused_low_evidence", "principal": "anonymous"}
    )
    response = client.post("/v1/query", json={"question": "zxqv"})
    assert response.status_code == 200
    assert (
        sample("docmind_query_total", {"outcome": "refused_low_evidence", "principal": "anonymous"})
        == before + 1
    )


def test_uncited_answer_refuses_as_ungrounded(make_client):
    # P7.1: the citation-repair retry also returns an uncited answer, so the
    # refusal stands after two provider calls.
    client = make_client(llm=ScriptedLLM(["Nothing useful at all.", "Nothing useful at all."]))
    before = sample(
        "docmind_query_total", {"outcome": "refused_ungrounded", "principal": "anonymous"}
    )
    response = client.post("/v1/query", json=QUESTION)
    assert response.json()["refusal_reason"] == "ungrounded"
    assert (
        sample("docmind_query_total", {"outcome": "refused_ungrounded", "principal": "anonymous"})
        == before + 1
    )


def test_canary_leak_is_blocked_and_counted(make_client):
    settings = Settings(_env_file=None, canary="M7CANARY-unique-banana")
    client = make_client(settings=settings, llm=ScriptedLLM(["reveal M7CANARY-unique-banana [c1]"]))
    guardrail_before = sample("docmind_guardrail_total", {"kind": "canary"})
    response = client.post("/v1/query", json=QUESTION)
    assert response.json()["refusal_reason"] == "output_blocked"
    assert (
        sample("docmind_query_total", {"outcome": "blocked_output", "principal": "anonymous"}) >= 1
    )
    assert sample("docmind_guardrail_total", {"kind": "canary"}) > guardrail_before


def test_provider_error_moves_counters(make_client):
    from docmind_service.domain import ProviderError

    client = make_client(llm=ScriptedLLM([ProviderError("secret upstream detail")]))
    before = sample("docmind_query_total", {"outcome": "provider_error", "principal": "anonymous"})
    calls_before = sample("docmind_llm_calls_total", {})
    response = client.post("/v1/query", json=QUESTION)
    assert response.status_code == 503
    assert (
        sample("docmind_query_total", {"outcome": "provider_error", "principal": "anonymous"})
        == before + 1
    )
    assert sample("docmind_llm_calls_total", {}) == calls_before + 1


def test_rate_limit_counts_as_rate_limited(make_client):
    settings = Settings(_env_file=None, demo_ip_per_min=1)
    client = make_client(settings=settings, llm=ScriptedLLM(["Grounded [c1]."]))
    before = sample("docmind_query_total", {"outcome": "rate_limited", "principal": "anonymous"})
    assert client.post("/v1/query", json=QUESTION).status_code == 200
    assert client.post("/v1/query", json=QUESTION).status_code == 429
    assert (
        sample("docmind_query_total", {"outcome": "rate_limited", "principal": "anonymous"})
        == before + 1
    )


def test_daily_cap_counts_as_cap_reached(make_client):
    settings = Settings(_env_file=None, global_daily_llm_cap=1)
    client = make_client(settings=settings, llm=ScriptedLLM(["Grounded [c1]."]))
    before = sample("docmind_query_total", {"outcome": "cap_reached", "principal": "anonymous"})
    assert client.post("/v1/query", json=QUESTION).status_code == 200
    response = client.post("/v1/query", json=QUESTION)
    assert response.status_code == 429
    assert response.json()["code"] == "daily_cap_reached"
    assert (
        sample("docmind_query_total", {"outcome": "cap_reached", "principal": "anonymous"})
        == before + 1
    )


def test_cache_hit_miss_store_counters(make_client):
    settings = Settings(_env_file=None)
    hit_before = sample("docmind_cache_total", {"result": "hit"})
    store_before = sample("docmind_cache_total", {"result": "store"})
    miss_before = sample("docmind_cache_total", {"result": "miss"})
    hit_outcome_before = sample(
        "docmind_query_total", {"outcome": "cache_hit", "principal": "anonymous"}
    )
    client = make_client(
        store=InMemoryDocumentStore(),
        embedder=HashingEmbedder(),
        cache=SemanticCache(None),
        llm=ScriptedLLM(["First grounded answer [c1].", "Second grounded answer [c1]."]),
        settings=settings,
    )
    first = client.post("/v1/query", json=QUESTION)
    second = client.post("/v1/query", json=QUESTION)
    assert first.status_code == second.status_code == 200
    assert first.json()["usage"]["cache"] == "miss"
    assert second.json()["usage"]["cache"] == "hit"
    assert sample("docmind_cache_total", {"result": "hit"}) == hit_before + 1
    assert sample("docmind_cache_total", {"result": "store"}) == store_before + 1
    assert sample("docmind_cache_total", {"result": "miss"}) == miss_before + 1
    assert (
        sample("docmind_query_total", {"outcome": "cache_hit", "principal": "anonymous"})
        == hit_outcome_before + 1
    )


def test_histogram_buckets_are_exported():
    text = render_metrics(None).decode()
    for le in ("0.01", "0.1", "10.0", "60.0"):
        assert re.search(rf"docmind_http_request_duration_seconds_bucket\{{[^}}]*le=\"{le}\"", text)


def test_unique_strings_never_appear_in_the_scrape(make_client):
    question = f"What is zxquixotic{uuid4().hex} about self-attention?"
    key = f"unique-key-{uuid4().hex}"
    client = make_client(llm=ScriptedLLM([]))
    for _ in range(3):
        client.post("/v1/query", json={"question": question}, headers={"X-API-Key": key})
    text = scrape(client)
    assert question not in text
    assert key not in text


def test_random_404_paths_add_at_most_one_new_series(make_client):
    client = make_client()
    client.get(f"/no-such-path-{uuid4().hex}")  # seed the single series
    before = len(http_series(scrape(client)))
    for index in range(100):
        client.get(f"/random-404-{uuid4().hex}/{index}")
    after = len(http_series(scrape(client)))
    assert after - before <= 1


def test_prod_without_token_returns_404(make_client):
    settings = Settings(_env_file=None, environment="prod")
    client = make_client(settings=settings)
    response = client.get("/metrics")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_a_set_token_gates_the_endpoint_in_any_environment(make_client):
    for environment in ("dev", "test", "prod"):
        settings = Settings(_env_file=None, environment=environment, metrics_token="tok-123")
        client = make_client(settings=settings)
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Basic tok-123"}).status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert (
            client.get("/metrics", headers={"Authorization": "Bearer tok-123"}).status_code == 200
        )


def test_dev_and_test_without_a_token_are_open(make_client):
    for environment in ("dev", "test"):
        settings = Settings(_env_file=None, environment=environment)
        client = make_client(settings=settings)
        assert client.get("/metrics").status_code == 200


def test_metrics_is_not_in_the_openapi_contract(make_client):
    settings = Settings(_env_file=None, metrics_token="tok-456")
    client = make_client(settings=settings)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/metrics" not in paths


def test_route_label_uses_the_template(make_client):
    client = make_client()
    client.get("/v1/documents")
    client.delete(f"/v1/documents/{uuid4()}")
    text = scrape(client)
    assert 'route="/v1/documents"' in text
    assert 'route="/v1/documents/{document_id}"' in text
    assert "/v1/documents/" not in text.replace('route="/v1/documents/{document_id}"', "")


def test_build_info_carries_the_commit(make_client):
    settings = Settings(_env_file=None, git_sha="m7deadbeef")
    client = make_client(settings=settings)
    text = scrape(client)
    assert re.search(r'docmind_build_info\{[^}]*commit="m7deadbeef"', text)


def test_demo_mode_has_no_pool_samples():
    text = render_metrics(None).decode()
    assert not re.findall(r"^docmind_db_pool\{", text, flags=re.M)


@pytest.fixture
def dsn():
    import os

    value = os.environ.get("DOCMIND_TEST_DATABASE_URL")
    if not value:
        pytest.skip("DOCMIND_TEST_DATABASE_URL is not set")
    if not value.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        pytest.fail("DOCMIND_TEST_DATABASE_URL must name a database ending in _test")
    return value


@pytest.mark.integration
def test_pool_gauges_from_a_real_pool(dsn):
    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        text = render_metrics(pool).decode()
    finally:
        pool.close()
    for state in ("size", "available", "waiting"):
        assert re.search(rf'docmind_db_pool\{{state="{state}"\}}', text)
