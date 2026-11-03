import argparse
import os
import sys
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

MIGRATIONS = Path(__file__).parent / "migrations"
ADVISORY_LOCK = 727001


def load_migrations() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"), key=lambda path: path.name)


def migrate(conninfo: str) -> list[str]:
    """Apply unapplied SQL migrations in filename order, one transaction each."""
    applied: list[str] = []
    with psycopg.connect(conninfo) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for path in load_migrations():
                version = path.stem
                if version in done:
                    continue
                sql = path.read_text(encoding="utf-8")
                with conn.transaction():
                    conn.execute(sql, prepare=False)
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK,))
    return applied


def migration_status(conninfo: str) -> list[str]:
    with psycopg.connect(conninfo) as conn:
        exists = conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0]
        if not exists:
            return []
        return [
            row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]


def print_status(conninfo: str) -> None:
    with psycopg.connect(conninfo) as conn:
        applied = migration_status(conninfo)
        extension = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        server = conn.execute("SELECT version()").fetchone()[0]
        counts = {}
        for table in ("documents", "chunks"):
            exists = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
            counts[table] = (
                conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] if exists else 0
            )
        size = conn.execute(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"
        ).fetchone()[0]
    print("applied: " + (", ".join(applied) if applied else "(none)"))
    print("vector: " + (extension[0] if extension else "(not installed)"))
    print("server: " + server)
    print(f"documents: {counts['documents']} rows")
    print(f"chunks: {counts['chunks']} rows")
    print("database size: " + size)


def make_pool(conninfo: str) -> ConnectionPool:
    return ConnectionPool(
        conninfo,
        min_size=1,
        max_size=5,
        timeout=10,
        max_idle=300,
        max_lifetime=1800,
        kwargs={"prepare_threshold": None},
        configure=register_vector,
        check=ConnectionPool.check_connection,
        open=False,
    )


def load_dotenv(path: str | Path) -> None:
    """Minimal .env loader: existing environment variables always win; values are never printed."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def load_local_env() -> None:
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m docmind_service.db")
    parser.add_argument("command", choices=["migrate", "status"])
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file)
    else:
        load_local_env()
    conninfo = os.environ.get("DOCMIND_DATABASE_URL_DIRECT") or os.environ.get(
        "DOCMIND_DATABASE_URL"
    )
    if not conninfo:
        print("DOCMIND_DATABASE_URL is not set", file=sys.stderr)
        return 2
    if args.command == "migrate":
        applied = migrate(conninfo)
        print("applied: " + (", ".join(applied) if applied else "(none)"))
    else:
        print_status(conninfo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
