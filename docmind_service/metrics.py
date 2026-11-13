"""Prometheus metrics and the /metrics access rule (M7.1)."""

from __future__ import annotations

import secrets
import time
from contextlib import contextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST as CONTENT_TYPE_LATEST,
)
from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from docmind_service import guardrails

HTTP_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

HTTP_REQUESTS = Counter(
    "docmind_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
HTTP_DURATION = Histogram(
    "docmind_http_request_duration_seconds",
    "HTTP request duration",
    ["route"],
    buckets=HTTP_BUCKETS,
    registry=REGISTRY,
)
QUERY_TOTAL = Counter(
    "docmind_query_total", "Queries by outcome", ["outcome", "principal"], registry=REGISTRY
)
LLM_CALLS = Counter("docmind_llm_calls_total", "Provider calls", registry=REGISTRY)
LLM_TOKENS = Counter("docmind_llm_tokens_total", "Provider tokens", ["kind"], registry=REGISTRY)
LLM_WAIT = Histogram("docmind_llm_wait_seconds", "Provider pacing wait", registry=REGISTRY)
LLM_API = Histogram("docmind_llm_api_seconds", "Provider API time", registry=REGISTRY)
LLM_SHED = Counter("docmind_llm_shed_total", "Requests shed by pacing", registry=REGISTRY)
GUARDRAIL = Counter("docmind_guardrail_total", "Guardrail events", ["kind"], registry=REGISTRY)
CACHE = Counter("docmind_cache_total", "Cache results", ["result"], registry=REGISTRY)
RETRIEVAL = Histogram("docmind_retrieval_seconds", "Retrieval time", registry=REGISTRY)
EMBED = Histogram("docmind_embed_seconds", "Embedding time", registry=REGISTRY)
RERANK_SECONDS = Histogram("docmind_rerank_seconds", "Cross-encoder rerank time", registry=REGISTRY)
RERANK_TOTAL = Counter("docmind_rerank_total", "Rerank results", ["result"], registry=REGISTRY)
DB_POOL = Gauge("docmind_db_pool", "Database pool state", ["state"], registry=REGISTRY)
DB_ERRORS = Counter("docmind_db_errors_total", "Database errors", registry=REGISTRY)
BUILD_INFO = Gauge(
    "docmind_build_info", "Build version and commit", ["version", "commit"], registry=REGISTRY
)

GUARDRAIL_KINDS = {
    "canary_blocked": "canary",
    "invalid_citations_removed": "invalid_citation",
    "ungrounded": "ungrounded",
    "images_removed": "image_removed",
    "urls_removed": "url_removed",
    "truncated": "truncated",
}
_guardrail_last = dict.fromkeys(GUARDRAIL_KINDS.values(), 0)


def route_template(request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "other"


def observe_request(route: str, method: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(route=route).observe(seconds)


def observe_query(outcome: str, *, anonymous: bool) -> None:
    QUERY_TOTAL.labels(outcome=outcome, principal="anonymous" if anonymous else "keyed").inc()
    sync_guardrails()


def observe_cache(result: str) -> None:
    CACHE.labels(result=result).inc()


def observe_llm(usage) -> None:
    if usage is None or not usage.calls:
        return
    LLM_CALLS.inc(usage.calls)
    if usage.prompt_tokens:
        LLM_TOKENS.labels(kind="prompt").inc(usage.prompt_tokens)
    if usage.completion_tokens:
        LLM_TOKENS.labels(kind="completion").inc(usage.completion_tokens)
    LLM_WAIT.observe(usage.wait_seconds)
    LLM_API.observe(usage.api_seconds)


def sync_guardrails() -> None:
    for counter, kind in GUARDRAIL_KINDS.items():
        current = guardrails.COUNTS.get(counter, 0)
        previous = _guardrail_last[kind]
        if current > previous:
            GUARDRAIL.labels(kind=kind).inc(current - previous)
        _guardrail_last[kind] = current


def set_build_info(version: str, commit: str | None) -> None:
    BUILD_INFO.labels(version=version or "unknown", commit=commit or "unknown").set(1)


def metrics_access(settings, authorization: str | None) -> str:
    """Return ``off``, ``unauthorized`` or ``open`` for the /metrics route."""
    expected = settings.metrics_token_value
    if not expected:
        return "off" if settings.environment == "prod" else "open"
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, expected):
        return "unauthorized"
    return "open"


def render_metrics(pool=None) -> bytes:
    sync_guardrails()
    if pool is not None:
        stats = pool.get_stats()
        DB_POOL.labels(state="size").set(stats.get("pool_size", 0))
        DB_POOL.labels(state="available").set(stats.get("pool_available", 0))
        DB_POOL.labels(state="waiting").set(stats.get("requests_waiting", 0))
    return generate_latest(REGISTRY)


@contextmanager
def timer(histogram):
    started = time.perf_counter()
    try:
        yield
    finally:
        histogram.observe(time.perf_counter() - started)
