import logging
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from docmind_service import __version__
from docmind_service.config import Settings, get_settings
from docmind_service.domain import LLMClient, ProviderError, RetrievalError, Retriever
from docmind_service.fakes import FakeLLM, InMemoryRetriever
from docmind_service.observability import configure_logging, request_context_middleware
from docmind_service.problem import (
    error_responses,
    http_exception_handler,
    problem_response,
    provider_error_handler,
    retrieval_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from docmind_service.query import PROMPT_VERSION, answer_question
from docmind_service.schemas import (
    Citation,
    DocumentList,
    DocumentOut,
    HealthOut,
    QueryIn,
    QueryOut,
    ReadyOut,
    Usage,
)

DESCRIPTION = (
    "Production-style RAG service over DocMind. Errors use application/problem+json (RFC 9457). "
    "API keys are declared in this contract and enforced from milestone M6."
)
NOT_IMPLEMENTED = "Not implemented yet: this route is part of the contract draft."

query_logger = logging.getLogger("docmind.query")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
v1 = APIRouter(prefix="/v1", dependencies=[Depends(api_key_header)])


@v1.post(
    "/documents",
    status_code=201,
    response_model=DocumentOut,
    tags=["documents"],
    summary="Upload a PDF",
    responses=error_responses(401, 413, 422, 429, 501, 503),
)
async def upload_document(file: Annotated[UploadFile, File()]) -> JSONResponse:
    return problem_response(501, NOT_IMPLEMENTED)


@v1.get(
    "/documents",
    response_model=DocumentList,
    tags=["documents"],
    summary="List documents",
    responses=error_responses(401, 429, 501, 503),
)
async def list_documents() -> JSONResponse:
    return problem_response(501, NOT_IMPLEMENTED)


@v1.delete(
    "/documents/{document_id}",
    status_code=204,
    tags=["documents"],
    summary="Delete a document and its chunks",
    responses=error_responses(401, 404, 422, 429, 501, 503),
)
async def delete_document(document_id: UUID) -> JSONResponse:
    return problem_response(501, NOT_IMPLEMENTED)


@v1.post(
    "/query",
    response_model=QueryOut,
    tags=["query"],
    summary="Ask a question",
    responses=error_responses(401, 422, 429, 501, 503),
)
def query(body: QueryIn, request: Request) -> QueryOut | JSONResponse:
    if body.mode == "multi":
        return problem_response(501, "Multi-agent mode is not implemented yet; use mode single.")
    state = request.app.state
    started = time.perf_counter()
    result = answer_question(
        body.question,
        retriever=state.retriever,
        llm=state.llm,
        document_ids=body.document_ids,
        top_k=body.top_k or state.settings.default_top_k,
    )
    llm = result.llm
    usage = Usage(
        calls=llm.calls if llm else 0,
        prompt_tokens=llm.prompt_tokens if llm else 0,
        completion_tokens=llm.completion_tokens if llm else 0,
        api_seconds=llm.api_seconds if llm else 0.0,
        wait_seconds=llm.wait_seconds if llm else 0.0,
        cache="bypass",
    )
    query_logger.info(
        "query",
        extra={
            "mode": body.mode,
            "prompt_version": PROMPT_VERSION,
            "n_chunks": result.n_chunks,
            "refused": result.refused,
            "invalid_citations": result.invalid_citations,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "cache": usage.cache,
        },
    )
    return QueryOut(
        answer=result.answer,
        citations=[
            Citation(document_id=c.document_id, page=c.page, chunk_id=c.chunk_id, score=c.score)
            for c in result.citations
        ],
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        usage=usage,
        request_id=request.state.request_id,
    )


def create_app(
    settings: Settings | None = None,
    retriever: Retriever | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="DocMind Service",
        version=__version__,
        description=DESCRIPTION,
        license_info={"name": "MIT"},
    )
    app.state.settings = settings
    app.state.retriever = retriever if retriever is not None else InMemoryRetriever()
    app.state.llm = llm if llm is not None else FakeLLM()
    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ProviderError, provider_error_handler)
    app.add_exception_handler(RetrievalError, retrieval_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/healthz", response_model=HealthOut, tags=["ops"], summary="Liveness")
    async def healthz() -> HealthOut:
        return HealthOut()

    @app.get(
        "/readyz",
        response_model=ReadyOut,
        tags=["ops"],
        summary="Readiness",
        responses={503: {"model": ReadyOut, "description": "A dependency is not ready"}},
    )
    async def readyz() -> JSONResponse:
        body = ReadyOut(
            status="not_ready",
            checks={
                "database": "not_configured",
                "embedder": "not_configured",
                "provider": "not_configured",
            },
        )
        return JSONResponse(body.model_dump(), status_code=503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse("# metrics are added in milestone M7\n", status_code=501)

    app.include_router(v1)
    return app


app = create_app()
