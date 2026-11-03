import threading
from types import SimpleNamespace

import httpx2
import pytest
from openai import APIConnectionError, APIStatusError, RateLimitError
from pydantic import SecretStr

from docmind_service.config import Settings
from docmind_service.domain import ProviderError
from docmind_service.llm import HostedLLM, TokenBucket


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.lock = threading.Lock()

    def create(self, **kwargs):
        with self.lock:
            self.calls.append(kwargs)
            result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def response(text="pong", prompt_tokens=12, completion_tokens=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def request():
    return httpx2.Request("POST", "https://provider.test/v1/chat/completions")


def settings(**overrides):
    values = {
        "llm_provider": "hosted",
        "llm_api_key": SecretStr("UNIQUE-SECRET-KEY-123"),
        "hosted_rpm": 1000,
        "hosted_tpm": 1000000,
        "llm_max_wait_seconds": 20,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_hosted_llm_returns_text_usage_and_required_request_fields():
    client = FakeClient([response()])
    llm = HostedLLM(settings(), client=client)
    result = llm.complete("hello")
    assert result.text == "pong"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert result.calls == 1
    call = client.chat.completions.calls[0]
    assert call["model"] == "openai/gpt-oss-120b"
    assert call["messages"][0]["content"] == "hello"
    assert call["max_completion_tokens"] == 1024
    assert call["reasoning_effort"] == "low"
    assert call["timeout"] == 60


def test_think_tags_are_stripped_and_empty_answers_fail():
    llm = HostedLLM(settings(), client=FakeClient([response("  <think>secret</think>ok  ")]))
    assert llm.complete("hello").text == "ok"
    empty = HostedLLM(settings(), client=FakeClient([response("<think>only</think>")]))
    with pytest.raises(ProviderError) as info:
        empty.complete("hello")
    assert info.value.retry_after == 5


def test_hosted_llm_retries_429_and_respects_retry_after():
    limited = RateLimitError(
        "slow down",
        response=httpx2.Response(429, headers={"retry-after": "0"}, request=request()),
        body=None,
    )
    client = FakeClient([limited, response("recovered")])
    waits = []
    result = HostedLLM(settings(), client=client, sleep=waits.append).complete("hello")
    assert result.text == "recovered"
    assert result.calls == 2
    assert waits == [0.5]


def test_429_message_parsing_covers_ms_s_and_m_s():
    for text, expected in [
        ("try again in 800ms", 1),
        ("try again in 7.5s", 8),
        ("try again in 2m3s", 123),
    ]:
        limited = RateLimitError(
            text,
            response=httpx2.Response(429, request=request()),
            body=None,
        )
        client = FakeClient([limited, response("recovered")])
        waits = []
        HostedLLM(settings(), client=client, sleep=waits.append).complete("hello")
        assert waits == [min(expected, 20) + 0.5]


def test_daily_quota_fails_fast_without_retry_or_body_leak():
    limited = RateLimitError(
        "tokens per day exceeded",
        response=httpx2.Response(429, headers={"retry-after": "3600"}, request=request()),
        body={"secret": "provider body"},
    )
    client = FakeClient([limited])
    with pytest.raises(ProviderError) as info:
        HostedLLM(settings(llm_max_wait_seconds=0), client=client).complete("hello")
    assert info.value.retry_after == 3600
    assert "provider body" not in str(info.value)
    assert len(client.chat.completions.calls) == 1


def test_413_and_auth_errors_are_sanitized():
    for status, expected in [(413, "request too large"), (401, "provider authentication failed")]:
        error = APIStatusError(
            "response body must not leak",
            response=httpx2.Response(status, request=request()),
            body=None,
        )
        with pytest.raises(ProviderError) as info:
            HostedLLM(settings(), client=FakeClient([error])).complete("hello")
        assert str(info.value) == expected
        assert "response body" not in str(info.value)


def test_connection_error_is_retried_once_then_fails_with_retry_after():
    error = APIConnectionError(request=request())
    client = FakeClient([error, error])
    waits = []
    with pytest.raises(ProviderError) as info:
        HostedLLM(settings(), client=client, sleep=waits.append).complete("hello")
    assert info.value.retry_after == 30
    assert waits == [1.0]
    assert len(client.chat.completions.calls) == 2


def test_retries_are_bounded_to_two():
    client = FakeClient(
        [
            RateLimitError("again", response=httpx2.Response(429, request=request()), body=None),
            RateLimitError("again", response=httpx2.Response(429, request=request()), body=None),
            RateLimitError("again", response=httpx2.Response(429, request=request()), body=None),
        ]
    )
    with pytest.raises(ProviderError):
        HostedLLM(settings(), client=client, sleep=lambda _: None).complete("hello")
    assert len(client.chat.completions.calls) == 3


def test_long_estimated_wait_is_shed_before_the_provider_is_called():
    client = FakeClient([response()])
    llm = HostedLLM(
        settings(hosted_rpm=2, hosted_tpm=100000, llm_max_wait_seconds=1), client=client
    )
    llm.complete("hello")
    with pytest.raises(ProviderError) as info:
        llm.complete("hello")
    assert info.value.retry_after is not None
    assert len(client.chat.completions.calls) == 1


def test_request_larger_than_the_token_bucket_is_rejected():
    with pytest.raises(ProviderError) as info:
        HostedLLM(settings(hosted_tpm=1000), client=FakeClient([response()])).complete("x" * 10000)
    assert "per-minute" in str(info.value)


def test_no_key_fails_before_calling_the_provider():
    with pytest.raises(ProviderError):
        HostedLLM(settings(llm_api_key=None)).complete("hello")


def test_secret_never_appears_in_exception_or_settings_repr():
    llm = HostedLLM(
        settings(),
        client=FakeClient(
            [
                APIStatusError(
                    "bad",
                    response=httpx2.Response(401, request=request()),
                    body={"key": "UNIQUE-SECRET-KEY-123"},
                )
            ]
        ),
    )
    with pytest.raises(ProviderError) as info:
        llm.complete("hello")
    assert "UNIQUE-SECRET-KEY-123" not in str(info.value)
    assert "UNIQUE-SECRET-KEY-123" not in repr(settings())


def test_token_bucket_refills_and_refunds():
    now = [0.0]
    bucket = TokenBucket(60, clock=lambda: now[0])
    assert bucket.take(30) == 0
    assert bucket.take(31) > 0
    now[0] = 32.0
    assert bucket.take(31) == 0
    bucket.give_back(10)
    assert bucket.take(10) == 0


def test_two_concurrent_callers_both_complete():
    client = FakeClient([response("one"), response("two")])
    llm = HostedLLM(settings(), client=client)
    results = []

    def call():
        results.append(llm.complete("hello").text)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["one", "two"]
    assert len(client.chat.completions.calls) == 2
