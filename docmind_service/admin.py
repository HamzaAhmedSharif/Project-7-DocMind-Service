"""Admin CLI: create, list and revoke API keys; inspect and purge the demo log."""

from __future__ import annotations

import argparse
import os
import sys

from docmind_service.auth import RESERVED_TENANTS, TENANT_RE, PgAuthStore
from docmind_service.db import load_dotenv, load_local_env, make_pool
from docmind_service.querylog import QueryLogWriter

BEGIN = "-----BEGIN DOCMIND KEY-----"
END = "-----END DOCMIND KEY-----"


def _open_pool(args):
    if args.env_file:
        load_dotenv(args.env_file)
    else:
        load_local_env()
    dsn = os.environ.get("DOCMIND_DATABASE_URL_DIRECT") or os.environ.get("DOCMIND_DATABASE_URL")
    if not dsn:
        print("DOCMIND_DATABASE_URL is not set", file=sys.stderr)
        return None
    pool = make_pool(dsn)
    pool.open(wait=True)
    return pool


def _create_key(store, args) -> int:
    if not TENANT_RE.fullmatch(args.tenant) or args.tenant in RESERVED_TENANTS:
        print(
            "tenant must match [a-z0-9][a-z0-9-]{1,30} and must not be public, eval or redteam",
            file=sys.stderr,
        )
        return 2
    scopes = ["read", "write"] if args.write else ["read"]
    record, full_key = store.create(
        tenant_id=args.tenant,
        label=args.label,
        scopes=scopes,
        rpm=args.rpm,
        daily_queries=args.daily,
        max_documents=args.max_docs,
        max_pages=args.max_pages,
    )
    print(BEGIN)
    print(full_key)
    print(END)
    print(f"prefix={record.prefix} tenant={record.tenant_id} scopes={','.join(record.scopes)}")
    return 0


def _list_keys(store) -> int:
    for record in store.list():
        revoked = record.revoked_at.isoformat() if record.revoked_at else "-"
        print(
            f"{record.prefix} tenant={record.tenant_id} label={record.label!r} "
            f"scopes={','.join(record.scopes)} created={record.created_at.isoformat()} "
            f"revoked={revoked}"
        )
    return 0


def _revoke(store, prefix: str) -> int:
    if store.revoke(prefix):
        print(f"revoked {prefix}")
        return 0
    print(f"not found or already revoked: {prefix}", file=sys.stderr)
    return 1


def _purge(pool) -> int:
    removed = QueryLogWriter(pool).purge_old()
    print(f"purged {removed} rows")
    return 0


def _show_log(pool, last: int) -> int:
    with pool.connection(timeout=3) as conn:
        rows = conn.execute(
            "SELECT question_redacted FROM query_log ORDER BY id DESC LIMIT %s", (last,)
        ).fetchall()
    for (text,) in reversed(rows):
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m docmind_service.admin")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-key", parents=[common])
    create.add_argument("--tenant", required=True)
    create.add_argument("--label", default="")
    create.add_argument("--write", action="store_true")
    create.add_argument("--rpm", type=int, default=None)
    create.add_argument("--daily", type=int, default=None)
    create.add_argument("--max-docs", type=int, default=None)
    create.add_argument("--max-pages", type=int, default=None)

    sub.add_parser("list-keys", parents=[common])
    revoke = sub.add_parser("revoke-key", parents=[common])
    revoke.add_argument("--prefix", required=True)
    sub.add_parser("purge-logs", parents=[common])
    show = sub.add_parser("show-log", parents=[common])
    show.add_argument("--last", type=int, default=10)

    args = parser.parse_args(argv)
    pool = _open_pool(args)
    if pool is None:
        return 2
    try:
        if args.command == "create-key":
            return _create_key(PgAuthStore(pool), args)
        if args.command == "list-keys":
            return _list_keys(PgAuthStore(pool))
        if args.command == "revoke-key":
            return _revoke(PgAuthStore(pool), args.prefix)
        if args.command == "purge-logs":
            return _purge(pool)
        return _show_log(pool, args.last)
    finally:
        pool.close()


if __name__ == "__main__":
    sys.exit(main())
