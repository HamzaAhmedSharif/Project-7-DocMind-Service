"""Redacted query log for the anonymous public demo (M6.6)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from docmind_service.redact import redact

logger = logging.getLogger("docmind.querylog")


class QueryLogWriter:
    """Insert one redacted row for anonymous queries; failures never fail the request."""

    def __init__(self, pool=None, days: int = 30, clock=lambda: datetime.now(UTC)):
        self.pool = pool
        self.days = days
        self._clock = clock
        self._last_purge: datetime | None = None
        self.rows: list[dict] = []

    def write(
        self,
        *,
        tenant_id: str,
        request_id: str,
        question: str,
        n_chunks: int,
        refused: bool,
        refusal_reason: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        cache: str,
        anonymous: bool,
    ) -> dict[str, int]:
        clean, counts = redact(question)
        if not anonymous:
            return counts
        row = {
            "ts": self._clock(),
            "tenant_id": tenant_id,
            "request_id": request_id,
            "question_redacted": clean,
            "n_chunks": n_chunks,
            "refused": refused,
            "refusal_reason": refusal_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache": cache,
        }
        try:
            self.maybe_purge()
            if self.pool is None:
                self.rows.append(row)
            else:
                with self.pool.connection(timeout=3) as conn:
                    conn.execute(
                        "INSERT INTO query_log "
                        "(tenant_id, request_id, question_redacted, n_chunks, refused, "
                        "refusal_reason, prompt_tokens, completion_tokens, cache) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            tenant_id,
                            request_id,
                            clean,
                            n_chunks,
                            refused,
                            refusal_reason,
                            prompt_tokens,
                            completion_tokens,
                            cache,
                        ),
                    )
        except Exception as exc:  # noqa: BLE001 - the request must not fail
            logger.warning(f"query log write failed [{type(exc).__name__}]")
        return counts

    def purge_old(self) -> int:
        cutoff = self._clock() - timedelta(days=self.days)
        if self.pool is None:
            before = len(self.rows)
            self.rows = [row for row in self.rows if row["ts"] >= cutoff]
            return before - len(self.rows)
        with self.pool.connection(timeout=3) as conn:
            row = conn.execute(
                "DELETE FROM query_log WHERE ts < %s RETURNING id", (cutoff,)
            ).fetchall()
        return len(row)

    def maybe_purge(self) -> None:
        now = self._clock()
        if self._last_purge is None or (now - self._last_purge).total_seconds() >= 86400:
            self.purge_old()
            self._last_purge = now
