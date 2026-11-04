"""API keys, principals and the short-lived key cache (M6.2)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request

KEY_RE = re.compile(r"^dm_([0-9a-f]{8})_([A-Za-z0-9_-]{32})$")
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
RESERVED_TENANTS = frozenset({"public", "eval", "redteam"})
TOUCH_SECONDS = 300
ANONYMOUS_TENANT = "public"


class InvalidKey(Exception):
    """A supplied X-API-Key is malformed, unknown or revoked."""


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    scopes: frozenset[str]
    key_id: str | None = None
    key_prefix: str | None = None
    anonymous: bool = False
    limits: dict = field(default_factory=dict)


@dataclass(frozen=True)
class KeyRecord:
    key_id: str
    tenant_id: str
    prefix: str
    key_hash: str
    label: str
    scopes: tuple[str, ...]
    rpm: int | None
    daily_queries: int | None
    max_documents: int | None
    max_pages: int | None
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Return ``(full_key, prefix, key_hash)``; the full key is shown only once."""
    prefix = secrets.token_hex(4)
    full_key = f"dm_{prefix}_{secrets.token_urlsafe(24)}"
    return full_key, prefix, hash_key(full_key)


def anonymous_principal(settings) -> Principal:
    return Principal(
        tenant_id=ANONYMOUS_TENANT,
        scopes=frozenset({"read"}),
        anonymous=True,
        limits={
            "rpm": settings.demo_ip_per_min,
            "daily_queries": settings.demo_daily_cap,
            "max_documents": settings.key_max_documents,
            "max_pages": settings.key_max_pages,
        },
    )


def _row_to_record(row) -> KeyRecord:
    return KeyRecord(
        key_id=str(row[0]),
        tenant_id=row[1],
        prefix=row[2],
        key_hash=row[3].strip() if isinstance(row[3], str) else row[3],
        label=row[4],
        scopes=tuple(row[5]),
        rpm=row[6],
        daily_queries=row[7],
        max_documents=row[8],
        max_pages=row[9],
        created_at=row[10],
        revoked_at=row[11],
        last_used_at=row[12],
    )


class PgAuthStore:
    """API-key table backed by Postgres."""

    COLUMNS = (
        "key_id, tenant_id, prefix, key_hash, label, scopes, rpm, daily_queries, "
        "max_documents, max_pages, created_at, revoked_at, last_used_at"
    )

    def __init__(self, pool):
        self.pool = pool

    def lookup(self, prefix: str) -> KeyRecord | None:
        with self.pool.connection(timeout=3) as conn:
            row = conn.execute(
                f"SELECT {self.COLUMNS} FROM api_keys WHERE prefix = %s", (prefix,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def create(
        self,
        *,
        tenant_id: str,
        label: str,
        scopes: list[str],
        rpm: int | None,
        daily_queries: int | None,
        max_documents: int | None,
        max_pages: int | None,
    ) -> tuple[KeyRecord, str]:
        full_key, prefix, key_hash = generate_key()
        with self.pool.connection(timeout=3) as conn:
            row = conn.execute(
                "INSERT INTO api_keys "
                "(tenant_id, prefix, key_hash, label, scopes, rpm, daily_queries, "
                "max_documents, max_pages) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                f"RETURNING {self.COLUMNS}",
                (
                    tenant_id,
                    prefix,
                    key_hash,
                    label,
                    scopes,
                    rpm,
                    daily_queries,
                    max_documents,
                    max_pages,
                ),
            ).fetchone()
        return _row_to_record(row), full_key

    def list(self) -> list[KeyRecord]:
        with self.pool.connection(timeout=3) as conn:
            rows = conn.execute(
                f"SELECT {self.COLUMNS} FROM api_keys ORDER BY created_at, prefix"
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def revoke(self, prefix: str) -> bool:
        with self.pool.connection(timeout=3) as conn:
            row = conn.execute(
                "UPDATE api_keys SET revoked_at = now() "
                "WHERE prefix = %s AND revoked_at IS NULL RETURNING key_id",
                (prefix,),
            ).fetchone()
        return row is not None

    def touch(self, prefix: str) -> None:
        with self.pool.connection(timeout=3) as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = now() WHERE prefix = %s "
                "AND (last_used_at IS NULL OR last_used_at < now() - interval '5 minutes')",
                (prefix,),
            )


class InMemoryAuthStore:
    """Test double mirroring PgAuthStore, with a settable clock."""

    def __init__(self, clock=lambda: datetime.now(UTC)):
        self._clock = clock
        self.records: dict[str, KeyRecord] = {}

    def lookup(self, prefix: str) -> KeyRecord | None:
        return self.records.get(prefix)

    def create(
        self,
        *,
        tenant_id: str,
        label: str = "",
        scopes: list[str] | None = None,
        rpm: int | None = None,
        daily_queries: int | None = None,
        max_documents: int | None = None,
        max_pages: int | None = None,
    ) -> tuple[KeyRecord, str]:
        full_key, prefix, key_hash = generate_key()
        record = KeyRecord(
            key_id=str(UUID(int=len(self.records) + 1)),
            tenant_id=tenant_id,
            prefix=prefix,
            key_hash=key_hash,
            label=label,
            scopes=tuple(scopes or ["read"]),
            rpm=rpm,
            daily_queries=daily_queries,
            max_documents=max_documents,
            max_pages=max_pages,
            created_at=self._clock(),
        )
        self.records[prefix] = record
        return record, full_key

    def list(self) -> list[KeyRecord]:
        return list(self.records.values())

    def revoke(self, prefix: str) -> bool:
        record = self.records.get(prefix)
        if record is None or record.revoked_at is not None:
            return False
        self.records[prefix] = KeyRecord(**{**record.__dict__, "revoked_at": self._clock()})
        return True

    def touch(self, prefix: str) -> None:
        record = self.records.get(prefix)
        if record is None:
            return
        now = self._clock()
        if record.last_used_at is not None and (now - record.last_used_at).total_seconds() < 300:
            return
        self.records[prefix] = KeyRecord(**{**record.__dict__, "last_used_at": now})


class AuthCache:
    """Resolve X-API-Key values; cache key rows for AUTH_CACHE_SECONDS."""

    def __init__(self, store, ttl_seconds: int = 60, clock=time.monotonic):
        self.store = store
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, KeyRecord | None]] = {}

    def _lookup(self, prefix: str) -> KeyRecord | None:
        now = self._clock()
        cached = self._cache.get(prefix)
        if cached is not None and now - cached[0] < self.ttl_seconds:
            return cached[1]
        record = self.store.lookup(prefix)
        self._cache[prefix] = (now, record)
        return record

    def resolve(self, header: str | None, settings) -> Principal:
        if header is None:
            return anonymous_principal(settings)
        match = KEY_RE.match(header)
        if not match:
            raise InvalidKey("malformed key")
        prefix = match.group(1)
        record = self._lookup(prefix)
        if record is None or record.revoked_at is not None:
            raise InvalidKey("unknown or revoked key")
        if not hmac.compare_digest(record.key_hash, hash_key(header)):
            raise InvalidKey("key mismatch")
        self.store.touch(prefix)
        return Principal(
            tenant_id=record.tenant_id,
            scopes=frozenset(record.scopes),
            key_id=record.key_id,
            key_prefix=record.prefix,
            anonymous=False,
            limits={
                "rpm": record.rpm or settings.key_rpm,
                "daily_queries": record.daily_queries or settings.key_daily_queries,
                "max_documents": record.max_documents or settings.key_max_documents,
                "max_pages": record.max_pages or settings.key_max_pages,
            },
        )


def get_principal(request: Request) -> Principal:
    """FastAPI dependency: anonymous without a header; 401 for any bad header."""
    state = request.app.state
    try:
        return state.auth.resolve(request.headers.get("X-API-Key"), state.settings)
    except InvalidKey as exc:
        raise HTTPException(
            status_code=401,
            detail="A valid X-API-Key is required for this key.",
            headers={"WWW-Authenticate": 'ApiKey realm="docmind"'},
        ) from exc
