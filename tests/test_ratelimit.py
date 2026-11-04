from datetime import UTC, datetime, timedelta

import pytest

from docmind_service.fakes import FakeLLM, InMemoryRetriever
from docmind_service.query import answer_question
from docmind_service.ratelimit import (
    CappedLLM,
    DailyCap,
    LimitExceeded,
    SlidingWindowLimiter,
    client_ip,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Request:
    def __init__(self, forwarded: str, host: str = "9.9.9.9") -> None:
        self.headers = {"x-forwarded-for": forwarded}
        self.client = type("Client", (), {"host": host})()


def test_window_math_and_retry_after():
    clock = Clock()
    limiter = SlidingWindowLimiter(2, 60, clock=clock)
    assert limiter.allow("a") == (True, 0.0)
    assert limiter.allow("a") == (True, 0.0)
    allowed, retry = limiter.allow("a")
    assert allowed is False
    assert 59 < retry <= 60
    clock.now = 60
    assert limiter.allow("a") == (True, 0.0)


def test_keys_are_independent():
    clock = Clock()
    limiter = SlidingWindowLimiter(1, 60, clock=clock)
    assert limiter.allow("a")[0] is True
    assert limiter.allow("b")[0] is True
    assert limiter.allow("a")[0] is False


def test_eviction_bound_keeps_the_newest_keys():
    limiter = SlidingWindowLimiter(1, 60, clock=Clock(), max_keys=2)
    for key in ("a", "b", "c"):
        limiter.allow(key)
    assert "a" not in limiter._keys
    assert len(limiter._keys) == 2


def test_client_ip_ignores_spoofed_left_entries():
    request = Request("1.1.1.1, 2.2.2.2, 3.3.3.3")
    assert client_ip(request, 0) == "9.9.9.9"
    assert client_ip(request, 1) == "3.3.3.3"
    assert client_ip(request, 2) == "2.2.2.2"
    assert client_ip(request, 4) == "9.9.9.9"


def test_daily_cap_memory_rollover():
    now = [datetime(2026, 11, 4, 23, 59, tzinfo=UTC)]
    cap = DailyCap(pool=None, limit=2, clock=lambda: now[0])
    assert cap.increment() == 1
    assert cap.increment() == 2
    assert cap.seconds_until_midnight() == 60
    now[0] += timedelta(minutes=2)
    assert cap.increment() == 1


def test_capped_llm_increments_before_the_provider_call():
    class Inner:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str):
            self.calls += 1
            return "ok"

    inner = Inner()
    llm = CappedLLM(inner, DailyCap(pool=None, limit=1))
    assert llm.complete("prompt") == "ok"
    with pytest.raises(LimitExceeded):
        llm.complete("prompt")
    assert inner.calls == 1


def test_no_evidence_refusal_does_not_increment_the_cap():
    cap = DailyCap(pool=None, limit=10)
    result = answer_question(
        "zzzz qqqq",
        retriever=InMemoryRetriever([]),
        llm=CappedLLM(FakeLLM(), cap),
        document_ids=None,
        top_k=3,
    )
    assert result.refused is True
    assert cap._memory == {}
