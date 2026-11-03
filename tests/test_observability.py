import io
import json
import logging
import re

from docmind_service.fakes import ScriptedLLM
from docmind_service.observability import JsonFormatter, resolve_request_id

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_generated_request_id_is_32_hex_chars(make_client):
    response = make_client().get("/healthz")
    assert HEX32.match(response.headers["x-request-id"])


def test_valid_incoming_request_id_is_echoed(make_client):
    response = make_client().get("/healthz", headers={"X-Request-ID": "abc-123_X.9"})
    assert response.headers["x-request-id"] == "abc-123_X.9"


def test_invalid_incoming_request_ids_are_replaced():
    for bad in ["has space", "semi;colon", "x" * 65, ""]:
        assert HEX32.match(resolve_request_id(bad))
    assert HEX32.match(resolve_request_id(None))


def test_access_log_has_one_record_per_request(make_client, log_records):
    response = make_client().get("/healthz", headers={"X-Request-ID": "trace-1"})
    access = [r for r in log_records if r.name == "docmind.access"]
    assert len(access) == 1
    record = access[0]
    assert (record.method, record.path, record.status) == ("GET", "/healthz", 200)
    assert record.duration_ms >= 0
    assert record.request_id == "trace-1"
    assert response.headers["x-request-id"] == "trace-1"


def test_logs_never_contain_the_question_or_the_answer(make_client, log_records):
    client = make_client(llm=ScriptedLLM(["UNIQUE-ANSWER-67890 [c1]"]))
    client.post("/v1/query", json={"question": "UNIQUE-QUESTION-12345 what is self-attention?"})
    formatter = JsonFormatter()
    lines = [formatter.format(r) for r in log_records]
    assert any('"message": "query"' in line for line in lines)
    assert not any("UNIQUE-QUESTION-12345" in line for line in lines)
    assert not any("UNIQUE-ANSWER-67890" in line for line in lines)


def test_json_formatter_outputs_valid_json_with_extras():
    logger = logging.getLogger("docmind.test")
    record = logger.makeRecord(
        "docmind.test",
        logging.INFO,
        __file__,
        1,
        "hello %s",
        ("world",),
        None,
        extra={"status": 200},
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "docmind.test"
    assert payload["status"] == 200
    assert "ts" in payload
    assert "request_id" in payload


def test_json_formatter_never_serialises_exception_messages():
    secret = "SECRET-" + "MESSAGE-777"
    try:
        raise ValueError(secret)
    except ValueError as exc:
        exc_info = (type(exc), exc, exc.__traceback__)
    record = logging.getLogger("docmind.test").makeRecord(
        "docmind.test", logging.ERROR, __file__, 1, "boom", (), exc_info
    )
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["exc_type"] == "ValueError"
    assert "exc_stack" in payload
    assert "SECRET-MESSAGE-777" not in line


def test_unhandled_exception_logs_never_contain_the_question(make_client, log_records):
    class LeakyRetriever:
        def retrieve(self, question, *, tenant_id="public", document_ids, top_k):
            raise RuntimeError(f"failed for {question}")

    client = make_client(retriever=LeakyRetriever(), raise_server_exceptions=False)
    response = client.post(
        "/v1/query", json={"question": "UNIQUE-QUESTION-12345 what is self-attention?"}
    )
    assert response.status_code == 500
    assert "UNIQUE-QUESTION-12345" not in response.text
    formatter = JsonFormatter()
    lines = [formatter.format(r) for r in log_records]
    errors = [json.loads(line) for line in lines if '"level": "ERROR"' in line]
    assert len(errors) == 1
    assert errors[0]["exc_type"] == "RuntimeError"
    assert not any("UNIQUE-QUESTION-12345" in line for line in lines)


def test_uvicorn_error_logs_drop_exception_messages(make_client):
    make_client()  # building the app installs the filter on the uvicorn.error logger
    secret = "SECRET-" + "MESSAGE-888"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(handler)
    try:
        try:
            raise ValueError(secret)
        except ValueError as exc:
            logger.error("Exception in ASGI application\n", exc_info=exc)
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert "ValueError" in output
    assert "SECRET-MESSAGE-888" not in output
