import json
import logging
import re
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import Request

from docmind_service.metrics import observe_request, route_template

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
access_logger = logging.getLogger("docmind.access")

_original_factory = logging.getLogRecordFactory()
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _record_factory(*args, **kwargs):
    record = _original_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    return record


def safe_exception_parts(exc_info) -> tuple[str, str]:
    """Exception type name and stack frames, never the exception message."""
    exc_type, _, tb = exc_info
    return exc_type.__name__, "".join(traceback.format_tb(tb))


class RedactExceptionFilter(logging.Filter):
    """Rewrite records that carry an exception to the type and stack frames only.

    A traceback ends with the exception message, which can contain user text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, stack = safe_exception_parts(record.exc_info)
            record.msg = f"{record.getMessage().rstrip()} [{exc_type}]\n{stack}"
            record.args = None
            record.exc_info = None
            record.exc_text = None
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per log line; extra fields passed to the logger are included."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload and not key.startswith("_"):
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"], payload["exc_stack"] = safe_exception_parts(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the docmind logger and tag every record with the request id."""
    logging.setLogRecordFactory(_record_factory)
    logger = logging.getLogger("docmind")
    for existing in list(logger.handlers):
        if existing.get_name() == "docmind-json":
            logger.removeHandler(existing)
    handler = logging.StreamHandler()
    handler.set_name("docmind-json")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    uvicorn_errors = logging.getLogger("uvicorn.error")
    if not any(isinstance(f, RedactExceptionFilter) for f in uvicorn_errors.filters):
        uvicorn_errors.addFilter(RedactExceptionFilter())


def resolve_request_id(incoming: str | None) -> str:
    """Keep an incoming id only if it is short and uses safe characters."""
    if incoming and _VALID_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


async def request_context_middleware(request: Request, call_next):
    request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        observe_request(
            route_template(request), request.method, status, time.perf_counter() - started
        )
        access_logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        request_id_var.reset(token)
