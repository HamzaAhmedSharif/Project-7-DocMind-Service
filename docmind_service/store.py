from uuid import UUID, uuid4

import numpy as np
import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from docmind_service.chunking import Chunk
from docmind_service.domain import DocumentRecord, Embedder, RetrievalError, RetrievedChunk


def _vector(values) -> str:
    """Text form accepted by pgvector's input parser."""
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


class PgStore:
    """Postgres + pgvector store; also implements the Retriever interface."""

    def __init__(self, pool: ConnectionPool, embedder: Embedder):
        self.pool = pool
        self.embedder = embedder
        self.dim = embedder.dim

    def ping(self) -> None:
        with self.pool.connection(timeout=3) as conn:
            conn.execute("SELECT 1").fetchone()

    def embedding_dimension(self) -> int | None:
        with self.pool.connection(timeout=3) as conn:
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            ).fetchone()
        if not row or not row[0].startswith("vector("):
            return None
        return int(row[0][7:-1])

    def _find(self, tenant_id: str, sha256: str) -> DocumentRecord | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT document_id, tenant_id, sha256, filename, pages, created_at, chunk_count "
                "FROM documents WHERE tenant_id = %s AND sha256 = %s",
                (tenant_id, sha256),
            ).fetchone()
        return self._record(row) if row else None

    def add_document(
        self,
        *,
        tenant_id: str,
        sha256: str,
        filename: str,
        pages: int,
        chunks: list[Chunk],
        embeddings: np.ndarray,
    ) -> tuple[DocumentRecord, bool]:
        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.shape != (len(chunks), self.dim):
            raise ValueError(
                f"embeddings shape {vectors.shape}, expected {(len(chunks), self.dim)}"
            )
        if not np.isfinite(vectors).all():
            raise ValueError("embeddings contain non-finite values")
        document_id = uuid4()
        with self.pool.connection() as conn:
            with conn.transaction():
                row = conn.execute(
                    "INSERT INTO documents "
                    "(document_id, tenant_id, sha256, filename, pages, chunk_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (tenant_id, sha256) DO NOTHING "
                    "RETURNING document_id, tenant_id, sha256, filename, pages, created_at, "
                    "chunk_count",
                    (document_id, tenant_id, sha256, filename, pages, len(chunks)),
                ).fetchone()
                if row is None:
                    existing = self._find(tenant_id, sha256)
                    if existing is None:
                        raise RuntimeError("conflict without an existing document")
                    return existing, False
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO chunks "
                        "(chunk_id, document_id, tenant_id, ordinal, page, text, embedding) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s::vector)",
                        [
                            (
                                f"{document_id}:{chunk.ordinal}",
                                document_id,
                                tenant_id,
                                chunk.ordinal,
                                chunk.page,
                                chunk.text,
                                _vector(vector),
                            )
                            for chunk, vector in zip(chunks, vectors, strict=True)
                        ],
                    )
        return self._record(row), True

    def _record(self, row) -> DocumentRecord:
        return DocumentRecord(
            document_id=row[0],
            tenant_id=row[1],
            sha256=row[2].strip() if isinstance(row[2], str) else row[2],
            filename=row[3],
            pages=row[4],
            created_at=row[5],
            chunk_count=row[6],
        )

    def list_documents(self, *, tenant_id: str) -> list[DocumentRecord]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT document_id, tenant_id, sha256, filename, pages, created_at, chunk_count "
                "FROM documents WHERE tenant_id = %s "
                "ORDER BY created_at DESC, document_id",
                (tenant_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def delete_document(self, *, tenant_id: str, document_id: UUID) -> bool:
        with self.pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM documents WHERE tenant_id = %s AND document_id = %s "
                "RETURNING document_id",
                (tenant_id, document_id),
            ).fetchone()
        return row is not None

    def retrieve(
        self,
        question: str,
        *,
        tenant_id: str,
        document_ids: list[UUID] | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        vector = np.asarray(self.embedder.embed_query(question), dtype=np.float32)
        if vector.shape != (self.dim,):
            raise ValueError(f"query embedding shape {vector.shape}, expected ({self.dim},)")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        literal = _vector(vector)
        docs = document_ids if document_ids else None
        query = (
            "SELECT chunk_id, document_id, page, text, 1 - (embedding <=> %(q)s::vector) AS score "
            "FROM chunks WHERE tenant_id = %(tenant)s "
            "AND (%(docs)s::uuid[] IS NULL OR document_id = ANY(%(docs)s)) "
            "ORDER BY embedding <=> %(q)s::vector LIMIT %(k)s"
        )
        try:
            with self.pool.connection() as conn:
                rows = conn.execute(
                    query, {"q": literal, "tenant": tenant_id, "docs": docs, "k": top_k}
                ).fetchall()
        except (psycopg.Error, PoolTimeout) as exc:
            raise RetrievalError("retrieval backend unavailable") from exc
        return [
            RetrievedChunk(
                chunk_id=row[0],
                document_id=row[1],
                page=row[2],
                text=row[3],
                score=float(row[4]),
            )
            for row in rows
        ]
