import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from docmind_service.auth import InMemoryAuthStore
from docmind_service.querylog import QueryLogWriter
from docmind_service.redact import redact

CASES = json.loads((Path(__file__).with_name("redaction_cases.json")).read_text(encoding="utf-8"))


def test_pii_recall_is_at_least_95_percent(capsys):
    hits = 0
    for case in CASES["pii"]:
        clean, _ = redact(case["text"])
        if f"[{case['kind'].upper()}]" in clean:
            hits += 1
        else:
            print(f"MISS {case['kind']}: {case['text']!r} -> {clean!r}")
    recall = hits / len(CASES["pii"])
    print(f"redaction recall: {hits}/{len(CASES['pii'])} = {recall:.3f}")
    assert recall >= 0.95


def test_benign_numbers_have_at_most_two_false_positives(capsys):
    changed = []
    for text in CASES["benign"]:
        clean, _ = redact(text)
        if clean != text:
            changed.append((text, clean))
    print(f"benign false positives: {len(changed)}/{len(CASES['benign'])}")
    for text, clean in changed:
        print(f"FALSE POSITIVE: {text!r} -> {clean!r}")
    assert len(changed) <= 2


def test_redaction_truncates_to_500_characters():
    clean, _ = redact("word " * 300)
    assert len(clean) <= 500


def test_names_are_not_redacted():
    clean, _ = redact("Alice Johnson asked about attention.")
    assert "Alice Johnson" in clean


def test_counts_are_reported_per_kind():
    clean, counts = redact("alice@example.com called 03001234567")
    assert "[EMAIL]" in clean
    assert "[PHONE]" in clean
    assert counts["email"] == 1
    assert counts["phone"] == 1


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def test_query_log_writes_anonymous_only():
    writer = QueryLogWriter(pool=None)
    writer.write(
        tenant_id="public",
        request_id="r1",
        question="What is attention?",
        n_chunks=1,
        refused=False,
        refusal_reason=None,
        prompt_tokens=10,
        completion_tokens=5,
        cache="miss",
        anonymous=True,
    )
    writer.write(
        tenant_id="t1",
        request_id="r2",
        question="What is attention?",
        n_chunks=1,
        refused=False,
        refusal_reason=None,
        prompt_tokens=10,
        completion_tokens=5,
        cache="miss",
        anonymous=False,
    )
    assert len(writer.rows) == 1
    assert writer.rows[0]["request_id"] == "r1"


def test_query_log_stores_redacted_text_only():
    writer = QueryLogWriter(pool=None)
    writer.write(
        tenant_id="public",
        request_id="r1",
        question="Email alice@example.com about " + "x" * 600,
        n_chunks=0,
        refused=True,
        refusal_reason="low_evidence",
        prompt_tokens=0,
        completion_tokens=0,
        cache="bypass",
        anonymous=True,
    )
    row = writer.rows[0]
    assert "alice@example.com" not in row["question_redacted"]
    assert "[EMAIL]" in row["question_redacted"]
    assert len(row["question_redacted"]) <= 500


def test_query_log_failure_is_swallowed_and_leaks_no_text(caplog):
    class BrokenPool:
        def connection(self, *args, **kwargs):
            raise RuntimeError("alice@example.com secret")

    writer = QueryLogWriter(pool=BrokenPool())
    with caplog.at_level(logging.WARNING, logger="docmind.querylog"):
        writer.write(
            tenant_id="public",
            request_id="r1",
            question="alice@example.com",
            n_chunks=0,
            refused=False,
            refusal_reason=None,
            prompt_tokens=0,
            completion_tokens=0,
            cache="bypass",
            anonymous=True,
        )
    assert "query log write failed [RuntimeError]" in caplog.text
    assert "alice@example.com" not in caplog.text


def test_query_log_retention_with_a_fake_clock():
    clock = Clock(datetime(2026, 11, 4, tzinfo=UTC))
    writer = QueryLogWriter(pool=None, days=30, clock=clock)
    writer.write(
        tenant_id="public",
        request_id="old",
        question="old question",
        n_chunks=0,
        refused=False,
        refusal_reason=None,
        prompt_tokens=0,
        completion_tokens=0,
        cache="bypass",
        anonymous=True,
    )
    clock.now += timedelta(days=31)
    assert writer.purge_old() == 1
    assert writer.rows == []


def test_unique_email_is_absent_but_a_normal_word_survives():
    writer = QueryLogWriter(pool=None)
    writer.write(
        tenant_id="public",
        request_id="r1",
        question="email unique-abc123@example.com about quantum bananas",
        n_chunks=0,
        refused=False,
        refusal_reason=None,
        prompt_tokens=0,
        completion_tokens=0,
        cache="bypass",
        anonymous=True,
    )
    row = writer.rows[0]
    assert "unique-abc123@example.com" not in row["question_redacted"]
    assert "quantum bananas" in row["question_redacted"]


def test_anonymous_query_is_logged_and_keyed_query_is_not(make_client):
    writer = QueryLogWriter(pool=None)
    client = make_client(query_log=writer)
    client.post("/v1/query", json={"question": "What is self-attention?"})
    assert len(writer.rows) == 1

    auth = InMemoryAuthStore()
    _, key = auth.create(tenant_id="t1")
    keyed = make_client(query_log=writer, auth_store=auth)
    keyed.post(
        "/v1/query",
        json={"question": "What is self-attention?"},
        headers={"X-API-Key": key},
    )
    assert len(writer.rows) == 1
