import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from docmind_service import __version__
from docmind_service.config import Settings, get_settings
from docmind_service.db import make_pool, migrate
from docmind_service.domain import LLMClient, ProviderError, RetrievalError, Retriever
from docmind_service.embedding import OnnxEmbedder
from docmind_service.fakes import FakeLLM, InMemoryRetriever
from docmind_service.ingest import IngestError, prepare_document
from docmind_service.llm import HostedLLM
from docmind_service.observability import configure_logging, request_context_middleware
from docmind_service.problem import (
    error_responses,
    http_exception_handler,
    limit_exceeded_handler,
    problem_response,
    provider_error_handler,
    retrieval_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from docmind_service.query import PROMPT_VERSION, answer_question
from docmind_service.ratelimit import (
    CappedLLM,
    DailyCap,
    LimitExceeded,
    SlidingWindowLimiter,
    client_ip,
)
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
from docmind_service.store import PgStore

DESCRIPTION = (
    "Production-style RAG service over DocMind. Errors use application/problem+json (RFC 9457). "
    "API keys are declared in this contract and enforced from milestone M6."
)
BYTE_STEP = 1024 * 1024
DEMO_DOCUMENTS = "Document storage needs DOCMIND_DATABASE_URL."
UPLOADS_DISABLED = "Uploads are disabled on this deployment."
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
STATIC_DIR = Path(__file__).resolve().parent / "static"

query_logger = logging.getLogger("docmind.query")
documents_logger = logging.getLogger("docmind.documents")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
v1 = APIRouter(prefix="/v1", dependencies=[Depends(api_key_header)])


def _document_out(record) -> DocumentOut:
    return DocumentOut(
        document_id=record.document_id,
        sha256=record.sha256,
        filename=record.filename,
        pages=record.pages,
        chunks=record.chunk_count,
        created_at=record.created_at,
    )


def _dependency_problem(detail: str = "The document service is unavailable.") -> JSONResponse:
    return problem_response(503, detail)


@v1.post(
    "/documents",
    status_code=201,
    response_model=DocumentOut,
    tags=["documents"],
    summary="Upload a PDF",
    responses={
        200: {"model": DocumentOut, "description": "Duplicate document; same sha256"},
        **error_responses(401, 411, 413, 422, 429, 503),
    },
)
def upload_document(file: Annotated[UploadFile, File()], request: Request) -> JSONResponse:
    state = request.app.state
    if not state.settings.uploads_enabled:
        return problem_response(403, UPLOADS_DISABLED)
    if state.demo:
        return problem_response(501, DEMO_DOCUMENTS)
    if state.store is None or state.embedder is None:
        return _dependency_problem("The document store or embedder is not configured.")
    max_bytes = state.settings.max_upload_mb * 1024 * 1024
    length_value = request.headers.get("content-length")
    if length_value is None:
        return problem_response(411, "Content-Length is required.")
    try:
        content_length = int(length_value)
    except ValueError:
        return problem_response(422, "Content-Length is invalid.")
    if content_length > max_bytes + BYTE_STEP:
        return problem_response(413, f"Upload exceeds the {state.settings.max_upload_mb} MB limit.")
    data = bytearray()
    while True:
        chunk = file.file.read(BYTE_STEP)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            return problem_response(
                413, f"Upload exceeds the {state.settings.max_upload_mb} MB limit."
            )
    try:
        prepared = prepare_document(
            bytes(data), file.filename or "upload.pdf", max_pages=state.settings.max_pages
        )
    except IngestError as exc:
        return problem_response(422, str(exc))
    try:
        batch_vectors = [
            state.embedder.embed_passages(
                [chunk.text for chunk in prepared.chunks[start : start + 32]]
            )
            for start in range(0, len(prepared.chunks), 32)
        ]
        embeddings = (
            np.vstack(batch_vectors) if batch_vectors else np.empty((0, state.embedder.dim))
        )
        record, created = state.store.add_document(
            tenant_id="public",
            sha256=prepared.sha256,
            filename=file.filename or "upload.pdf",
            pages=len(prepared.pages),
            chunks=prepared.chunks,
            embeddings=embeddings,
        )
    except Exception:
        documents_logger.exception("document upload failed")
        return _dependency_problem()
    return JSONResponse(
        status_code=201 if created else 200,
        content=_document_out(record).model_dump(mode="json"),
    )


@v1.get(
    "/documents",
    response_model=DocumentList,
    tags=["documents"],
    summary="List documents",
    responses=error_responses(401, 429, 501, 503),
)
def list_documents(request: Request) -> DocumentList | JSONResponse:
    state = request.app.state
    if state.demo:
        return problem_response(501, DEMO_DOCUMENTS)
    if state.store is None:
        return _dependency_problem("The document store is not configured.")
    try:
        records = state.store.list_documents(tenant_id="public")
    except Exception:
        documents_logger.exception("document list failed")
        return _dependency_problem()
    return DocumentList(items=[_document_out(record) for record in records])


@v1.delete(
    "/documents/{document_id}",
    status_code=204,
    response_model=None,
    tags=["documents"],
    summary="Delete a document and its chunks",
    responses=error_responses(401, 404, 422, 429, 501, 503),
)
def delete_document(document_id: UUID, request: Request) -> Response | JSONResponse:
    state = request.app.state
    if not state.settings.uploads_enabled:
        return problem_response(403, UPLOADS_DISABLED)
    if state.demo:
        return problem_response(501, DEMO_DOCUMENTS)
    if state.store is None:
        return _dependency_problem("The document store is not configured.")
    try:
        deleted = state.store.delete_document(tenant_id="public", document_id=document_id)
    except Exception:
        documents_logger.exception("document delete failed")
        return _dependency_problem()
    if not deleted:
        return problem_response(404, "Document not found.")
    return Response(status_code=204)


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
    allowed, retry_after = state.limiter.allow(client_ip(request, state.settings.trust_proxy_hops))
    if not allowed:
        raise LimitExceeded("rate_limited", retry_after)
    started = time.perf_counter()
    result = answer_question(
        body.question,
        tenant_id="public",
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
    store=None,
    embedder=None,
) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    configure_logging(settings.log_level)
    dsn = settings.database_url_value
    demo = store is None and not dsn
    pool = None
    if not demo and store is None:
        pool = make_pool(dsn)
        if embedder is None:
            embedder = OnnxEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir)
        store = PgStore(pool, embedder)
    if retriever is None:
        retriever = (
            store if store is not None and hasattr(store, "retrieve") else InMemoryRetriever()
        )
    if llm is None:
        llm = HostedLLM(settings) if settings.llm_provider == "hosted" else FakeLLM()
    if isinstance(llm, FakeLLM) or settings.llm_provider == "fake":
        provider_status = "fake"
    elif settings.llm_provider == "hosted":
        provider_status = "configured" if settings.llm_api_key_value else "not_configured"
    else:
        provider_status = "configured"

    daily_cap = DailyCap(pool, settings.demo_daily_cap)
    llm = CappedLLM(llm, daily_cap)
    limiter = SlidingWindowLimiter(settings.demo_ip_per_min, 60.0)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            direct_dsn = settings.database_url_direct_value or settings.database_url_value
            if settings.auto_migrate and direct_dsn:
                migrate(direct_dsn)
            if pool is not None:
                pool.open(wait=True)
            warm_up = getattr(embedder, "warm_up", None)
            if warm_up is not None:
                warm_up()
            yield
        finally:
            if pool is not None:
                pool.close()

    app = FastAPI(
        title="DocMind Service",
        version=__version__,
        description=DESCRIPTION,
        license_info={"name": "MIT"},
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.demo = demo
    app.state.pool = pool
    app.state.store = store
    app.state.embedder = embedder
    app.state.retriever = retriever
    app.state.llm = llm
    app.state.limiter = limiter
    app.state.daily_cap = daily_cap
    app.state.provider_status = provider_status
    app.state.git_sha = settings.commit_sha
    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ProviderError, provider_error_handler)
    app.add_exception_handler(RetrievalError, retrieval_error_handler)
    app.add_exception_handler(LimitExceeded, limit_exceeded_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = CSP
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def landing() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/healthz", response_model=HealthOut, tags=["ops"], summary="Liveness")
    async def healthz() -> HealthOut:
        return HealthOut(version=__version__, commit=settings.commit_sha)

    @app.get(
        "/readyz",
        response_model=ReadyOut,
        tags=["ops"],
        summary="Readiness",
        responses={503: {"model": ReadyOut, "description": "A dependency is not ready"}},
    )
    async def readyz() -> JSONResponse:
        if demo:
            body = ReadyOut(
                status="ready",
                checks={"database": "demo", "embedder": "demo", "provider": "demo"},
            )
            return JSONResponse(body.model_dump(), status_code=200)
        checks = {
            "database": "not_configured",
            "embedder": "not_configured",
            "provider": provider_status,
        }
        if store is not None:
            try:
                store.ping()
                expected = getattr(embedder, "dim", 384)
                dimension = store.embedding_dimension()
                checks["database"] = "ok" if dimension == expected else "DimensionMismatch"
            except Exception as exc:
                checks["database"] = type(exc).__name__
        if embedder is not None:
            try:
                vector = embedder.embed_query("readiness")
                checks["embedder"] = "ok" if len(vector) == embedder.dim else "DimensionMismatch"
            except Exception as exc:
                checks["embedder"] = type(exc).__name__
        ready = checks["database"] == "ok" and checks["embedder"] == "ok"
        body = ReadyOut(status="ready" if ready else "not_ready", checks=checks)
        return JSONResponse(body.model_dump(), status_code=200 if ready else 503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse("# metrics are added in milestone M7\n", status_code=501)

    app.include_router(v1)
    return app


app = create_app()
