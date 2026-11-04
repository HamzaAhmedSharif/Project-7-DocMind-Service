import logging
import math
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from docmind_service.domain import ProviderError, RetrievalError
from docmind_service.observability import REQUEST_ID_HEADER, request_id_var
from docmind_service.ratelimit import LimitExceeded
from docmind_service.schemas import Problem

PROBLEM_JSON = "application/problem+json"
unhandled_logger = logging.getLogger("docmind.app")

TITLES = {
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    411: "Length Required",
    413: "Payload Too Large",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    501: "Not Implemented",
    503: "Service Unavailable",
}


def problem_response(
    status: int,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    request_id: str | None = None,
    code: str | None = None,
) -> JSONResponse:
    """Build an RFC 9457 problem details response that carries the request id."""
    body = Problem(
        title=TITLES.get(status, "Error"),
        status=status,
        detail=detail,
        request_id=request_id or request_id_var.get(),
        code=code,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI response entries for error statuses, all documented as Problem."""
    return {
        status: {"model": Problem, "description": f"{TITLES[status]} (application/problem+json)"}
        for status in statuses
    }


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return problem_response(exc.status_code, str(exc.detail), exc.headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", "invalid request")
    return problem_response(422, f"{location}: {message}" if location else message)


async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    retry_after = min(max(exc.retry_after or 30, 1), 300)
    detail = "The language model provider is unavailable."
    return problem_response(503, detail, headers={"Retry-After": str(retry_after)})


async def retrieval_error_handler(request: Request, exc: RetrievalError) -> JSONResponse:
    detail = "The retrieval backend is unavailable."
    return problem_response(503, detail, headers={"Retry-After": "30"})


async def limit_exceeded_handler(request: Request, exc: LimitExceeded) -> JSONResponse:
    retry_after = str(max(1, math.ceil(exc.retry_after)))
    if exc.code == "daily_cap_reached":
        detail = "The daily question cap has been reached. Try again after midnight UTC."
    else:
        detail = "Too many requests from this address. Try again shortly."
    headers = {**exc.headers, "Retry-After": retry_after}
    return problem_response(429, detail, headers=headers, code=exc.code)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    token = request_id_var.set(request_id)
    try:
        unhandled_logger.error("unhandled exception", exc_info=exc)
    finally:
        request_id_var.reset(token)
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return problem_response(500, "Internal server error.", headers=headers, request_id=request_id)
