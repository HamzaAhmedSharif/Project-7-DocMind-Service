from datetime import UTC, datetime
from uuid import UUID, uuid4

from docmind_service.domain import DocumentRecord
from docmind_service.embedding import HashingEmbedder
from docmind_service.fakes import ScriptedLLM
from scripts.make_tiny_pdf import make_pdf

LONG = "This page contains enough text to pass the extraction check. " * 4


class FakeStore:
    def __init__(self):
        self.records: dict[tuple[str, str], DocumentRecord] = {}

    def ping(self):
        return None

    def embedding_dimension(self):
        return 384

    def add_document(self, *, tenant_id, sha256, filename, pages, chunks, embeddings):
        key = (tenant_id, sha256)
        existing = self.records.get(key)
        if existing is not None:
            return existing, False
        record = DocumentRecord(
            document_id=uuid4(),
            tenant_id=tenant_id,
            sha256=sha256,
            filename=filename,
            pages=pages,
            chunk_count=len(chunks),
            created_at=datetime.now(UTC),
        )
        self.records[key] = record
        return record, True

    def list_documents(self, *, tenant_id):
        return [record for (tenant, _), record in self.records.items() if tenant == tenant_id]

    def delete_document(self, *, tenant_id, document_id: UUID):
        for key, record in list(self.records.items()):
            if key[0] == tenant_id and record.document_id == document_id:
                del self.records[key]
                return True
        return False


class BrokenStore(FakeStore):
    def ping(self):
        raise RuntimeError("database secret detail")

    def add_document(self, **kwargs):
        raise RuntimeError("database secret detail")

    def list_documents(self, **kwargs):
        raise RuntimeError("database secret detail")

    def delete_document(self, **kwargs):
        raise RuntimeError("database secret detail")


def upload(client, data=None, filename="paper.pdf"):
    return client.post(
        "/v1/documents",
        files={"file": (filename, data or make_pdf([LONG]), "application/pdf")},
    )


def test_upload_list_and_delete_roundtrip(make_client):
    store = FakeStore()
    client = make_client(store=store, embedder=HashingEmbedder())
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "paper.pdf"
    assert body["pages"] == 1
    assert body["chunks"] >= 1
    assert len(body["sha256"]) == 64

    again = upload(client)
    assert again.status_code == 200
    assert again.json()["document_id"] == body["document_id"]

    listed = client.get("/v1/documents")
    assert listed.status_code == 200
    assert [item["document_id"] for item in listed.json()["items"]] == [body["document_id"]]

    deleted = client.delete(f"/v1/documents/{body['document_id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get("/v1/documents").json()["items"] == []
    assert client.delete(f"/v1/documents/{body['document_id']}").status_code == 404


def test_upload_rejects_non_pdf_and_oversized_files(make_client):
    client = make_client(store=FakeStore(), embedder=HashingEmbedder())
    non_pdf = client.post("/v1/documents", files={"file": ("x.txt", b"not a pdf", "text/plain")})
    assert non_pdf.status_code == 422
    assert non_pdf.headers["content-type"].startswith("application/problem+json")

    from docmind_service.config import Settings

    small_limit = make_client(
        store=FakeStore(),
        embedder=HashingEmbedder(),
        settings=Settings(_env_file=None, max_upload_mb=1),
    )
    too_big = small_limit.post(
        "/v1/documents", files={"file": ("big.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")}
    )
    assert too_big.status_code == 413
    assert "MB" in too_big.json()["detail"]


def test_upload_without_extractable_text_is_422(make_client):
    from docmind_service.ingest import IngestError, extract_pages

    data = make_pdf(["", ""])
    try:
        extract_pages(data, max_pages=10)
    except IngestError as exc:
        assert exc.code == "no_text"
    response = upload(make_client(store=FakeStore(), embedder=HashingEmbedder()), data)
    assert response.status_code == 422


def test_store_failure_is_a_safe_503(make_client):
    client = make_client(store=BrokenStore(), embedder=HashingEmbedder())
    response = upload(client)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "secret detail" not in response.text


def test_readyz_reports_real_components(make_client):
    response = make_client(store=FakeStore(), embedder=HashingEmbedder(), llm=ScriptedLLM([])).get(
        "/readyz"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "embedder": "ok", "provider": "fake"},
    }


def test_readyz_reports_a_broken_database_without_leaking_it(make_client):
    response = make_client(
        store=BrokenStore(), embedder=HashingEmbedder(), llm=ScriptedLLM([])
    ).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "RuntimeError"
    assert "secret detail" not in response.text
