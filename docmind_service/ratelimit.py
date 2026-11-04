"""Demo guard (M5.1): per-IP window, persistent daily cap, upload switch."""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime, timedelta


class SlidingWindowLimiter:
    """Per-key sliding window. Memory is bounded to ``max_keys`` keys."""

    def __init__(
        self, limit: int, window_seconds: float, clock=time.monotonic, max_keys: int = 10_000
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._keys: dict[str, deque[float]] = {}

    def allow(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``."""
        if self.limit <= 0:
            return False, self.window_seconds
        now = self._clock()
        bucket = self._keys.setdefault(key, deque())
        while bucket and now - bucket[0] >= self.window_seconds:
            bucket.popleft()
        if len(bucket) < self.limit:
            bucket.append(now)
            allowed, retry = True, 0.0
        else:
            allowed, retry = False, bucket[0] + self.window_seconds - now
        if len(self._keys) > self._max_keys:
            self._evict()
        return allowed, max(retry, 0.0)

    def _evict(self) -> None:
        for key in [k for k, bucket in self._keys.items() if not bucket]:
            del self._keys[key]
        while len(self._keys) > self._max_keys:
            oldest = min(self._keys, key=lambda k: self._keys[k][0])
            del self._keys[oldest]


class DailyCap:
    """UTC-day counter in Postgres, or in memory when there is no database."""

    def __init__(self, pool=None, limit: int = 300, clock=lambda: datetime.now(UTC)):
        self._pool = pool
        self.limit = limit
        self._clock = clock
        self._memory: dict[tuple[str, str], int] = {}

    def increment(self, scope: str = "public") -> int:
        now = self._clock()
        day = now.date().isoformat()
        if self._pool is None:
            key = (day, scope)
            self._memory[key] = self._memory.get(key, 0) + 1
            return self._memory[key]
        with self._pool.connection(timeout=3) as conn:
            row = conn.execute(
                "INSERT INTO usage_daily (day, scope, count) VALUES (%s, %s, 1) "
                "ON CONFLICT (day, scope) DO UPDATE SET count = usage_daily.count + 1 "
                "RETURNING count",
                (day, scope),
            ).fetchone()
        return int(row[0])

    def seconds_until_midnight(self) -> float:
        now = self._clock()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(0.0, (tomorrow - now).total_seconds())


class LimitExceeded(Exception):
    def __init__(self, code: str, retry_after: float = 0.0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


class CappedLLM:
    """Increment the daily counter before each provider call; raise when over the cap."""

    def __init__(self, inner, cap: DailyCap, scope: str = "public"):
        self.inner = inner
        self.cap = cap
        self.scope = scope

    def complete(self, prompt: str):
        if self.cap.increment(self.scope) > self.cap.limit:
            raise LimitExceeded("daily_cap_reached", self.cap.seconds_until_midnight())
        return self.inner.complete(prompt)


def client_ip(request, hops: int) -> str:
    """Take the ``hops``-th X-Forwarded-For entry from the right; fall back to the peer."""
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
