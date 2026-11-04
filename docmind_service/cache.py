"""Persistent semantic cache keyed by tenant, corpus version and request scope (M6.7)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np


def scope_hash(
    *,
    document_ids,
    top_k: int,
    mode: str,
    prompt_version: str,
    model_name: str,
    guardrails_enabled: bool,
    evidence_min_score: float,
    require_citation: bool,
) -> str:
    payload = {
        "document_ids": sorted(str(item) for item in document_ids) if document_ids else None,
        "top_k": top_k,
        "mode": mode,
        "prompt_version": prompt_version,
        "model": model_name,
        "guardrails_enabled": guardrails_enabled,
        "evidence_min_score": round(float(evidence_min_score), 6),
        "require_citation": require_citation,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def _vector(values) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


@dataclass
class CacheRow:
    tenant_id: str
    corpus_version: str
    scope_hash: str
    embedding: np.ndarray
    answer_json: dict
    created_at: datetime
    hits: int = 0


class SemanticCache:
    """Postgres-backed cache; ``pool=None`` gives the in-memory test double."""

    def __init__(
        self,
        pool=None,
        *,
        ttl_days: int = 30,
        max_rows: int = 500,
        clock=lambda: datetime.now(UTC),
    ):
        self.pool = pool
        self.ttl_days = ttl_days
        self.max_rows = max_rows
        self._clock = clock
        self.rows: list[CacheRow] = []
        self._last_purge: datetime | None = None

    def lookup(
        self,
        *,
        tenant_id: str,
        corpus_version: str,
        scope_hash: str,
        embedding,
        threshold: float,
    ) -> dict | None:
        cutoff = self._clock() - timedelta(days=self.ttl_days)
        if self.pool is None:
            candidates = [
                row
                for row in self.rows
                if row.tenant_id == tenant_id
                and row.corpus_version == corpus_version
                and row.scope_hash == scope_hash
                and row.created_at >= cutoff
            ]
            if not candidates:
                return None
            best = max(candidates, key=lambda row: _cosine(row.embedding, embedding))
            if _cosine(best.embedding, embedding) < threshold:
                return None
            best.hits += 1
            return best.answer_json
        with self.pool.connection(timeout=3) as conn:
            row = conn.execute(
                "SELECT id, answer_json, 1 - (question_embedding <=> %s::vector) AS similarity "
                "FROM semantic_cache WHERE tenant_id = %s AND corpus_version = %s "
                "AND scope_hash = %s AND created_at >= %s "
                "ORDER BY question_embedding <=> %s::vector LIMIT 1",
                (
                    _vector(embedding),
                    tenant_id,
                    corpus_version,
                    scope_hash,
                    cutoff,
                    _vector(embedding),
                ),
            ).fetchone()
            if row is None or float(row[2]) < threshold:
                return None
            conn.execute("UPDATE semantic_cache SET hits = hits + 1 WHERE id = %s", (row[0],))
        return row[1]

    def store(
        self,
        *,
        tenant_id: str,
        corpus_version: str,
        scope_hash: str,
        embedding,
        answer_json: dict,
    ) -> None:
        if self.pool is None:
            self.rows.append(
                CacheRow(
                    tenant_id=tenant_id,
                    corpus_version=corpus_version,
                    scope_hash=scope_hash,
                    embedding=np.asarray(embedding, dtype=np.float32),
                    answer_json=answer_json,
                    created_at=self._clock(),
                )
            )
            self._evict(tenant_id)
            return
        with self.pool.connection(timeout=3) as conn:
            conn.execute(
                "INSERT INTO semantic_cache "
                "(tenant_id, corpus_version, scope_hash, question_embedding, answer_json) "
                "VALUES (%s, %s, %s, %s::vector, %s::jsonb)",
                (
                    tenant_id,
                    corpus_version,
                    scope_hash,
                    _vector(embedding),
                    json.dumps(answer_json),
                ),
            )
            conn.execute(
                "DELETE FROM semantic_cache WHERE tenant_id = %s AND id NOT IN "
                "(SELECT id FROM semantic_cache WHERE tenant_id = %s "
                "ORDER BY created_at DESC, id DESC LIMIT %s)",
                (tenant_id, tenant_id, self.max_rows),
            )

    def _evict(self, tenant_id: str) -> None:
        mine = [row for row in self.rows if row.tenant_id == tenant_id]
        if len(mine) <= self.max_rows:
            return
        keep = {id(row) for row in sorted(mine, key=lambda row: row.created_at)[-self.max_rows :]}
        self.rows = [row for row in self.rows if row.tenant_id != tenant_id or id(row) in keep]

    def purge(self, *, tenant_id: str | None = None, corpus_version: str | None = None) -> int:
        cutoff = self._clock() - timedelta(days=self.ttl_days)
        if self.pool is None:
            before = len(self.rows)

            def keep(row: CacheRow) -> bool:
                if row.created_at < cutoff:
                    return False
                if tenant_id is None or row.tenant_id != tenant_id:
                    return True
                return corpus_version is None or row.corpus_version == corpus_version

            self.rows = [row for row in self.rows if keep(row)]
            return before - len(self.rows)
        with self.pool.connection(timeout=3) as conn:
            if tenant_id is None:
                rows = conn.execute(
                    "DELETE FROM semantic_cache WHERE created_at < %s RETURNING id", (cutoff,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "DELETE FROM semantic_cache WHERE tenant_id = %s AND "
                    "(created_at < %s OR corpus_version <> %s) RETURNING id",
                    (tenant_id, cutoff, corpus_version or ""),
                ).fetchall()
        return len(rows)

    def maybe_purge(self, *, tenant_id: str, corpus_version: str) -> None:
        now = self._clock()
        if self._last_purge is None or (now - self._last_purge).total_seconds() >= 3600:
            self.purge(tenant_id=tenant_id, corpus_version=corpus_version)
            self._last_purge = now
