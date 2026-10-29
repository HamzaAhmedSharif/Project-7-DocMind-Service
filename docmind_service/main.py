from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from docmind_service import __version__
from docmind_service.problem import (
    error_responses,
    http_exception_handler,
    problem_response,
    validation_exception_handler,
)
from docmind_service.schemas import (
    DocumentList,
    DocumentOut,
    HealthOut,
    QueryIn,
    QueryOut,
    ReadyOut,
)

DESCRIPTION = (
    "Production-style RAG service over DocMind. Errors use application/problem+json (RFC 9457). "
    "API keys are declared in this contract and enforced from milestone M6."
)
NOT_IMPLEMENTED = "Not implemented yet: this route is part of the contract draft."

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
async def query(body: QueryIn) -> JSONResponse:
    return problem_response(501, NOT_IMPLEMENTED)


def create_app() -> FastAPI:
    app = FastAPI(
        title="DocMind Service",
        version=__version__,
        description=DESCRIPTION,
        license_info={"name": "MIT"},
    )
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

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
