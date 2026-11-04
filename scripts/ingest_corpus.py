"""Download, verify and ingest the demo corpus (M5.2). Prints counts only."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docmind_service.config import Settings  # noqa: E402
from docmind_service.db import load_dotenv, make_pool  # noqa: E402
from docmind_service.embedding import OnnxEmbedder  # noqa: E402
from docmind_service.ingest import prepare_document  # noqa: E402
from docmind_service.store import PgStore  # noqa: E402
from scripts.fetch_corpus import fetch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the demo corpus.")
    parser.add_argument("--manifest", default="evaluation/demo_corpus.json")
    parser.add_argument("--tenant", default="public")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--data-dir", default="data/demo")
    args = parser.parse_args(argv)

    load_dotenv(args.env_file) if args.env_file else load_dotenv(ROOT / ".env")
    settings = Settings(_env_file=None)
    dsn = settings.database_url_value
    if not dsn:
        print("DOCMIND_DATABASE_URL is not set", file=sys.stderr)
        return 2

    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
    data_dir = ROOT / args.data_dir
    pool = make_pool(dsn)
    pool.open(wait=True)
    started = time.perf_counter()
    try:
        embedder = OnnxEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir)
        store = PgStore(pool, embedder)
        for item in manifest["corpora"]:
            path = data_dir / f"{item['id']}.pdf"
            fetch(item["url"], path, item["sha256"])
            prepared = prepare_document(
                path.read_bytes(), f"{item['id']}.pdf", max_pages=settings.max_pages
            )
            embeddings = embedder.embed_passages([chunk.text for chunk in prepared.chunks])
            record, created = store.add_document(
                tenant_id=args.tenant,
                sha256=prepared.sha256,
                filename=item["title"],
                pages=len(prepared.pages),
                chunks=prepared.chunks,
                embeddings=embeddings,
            )
            print(f"{item['id']}: documents=1 chunks={record.chunk_count} created={created}")
        print(
            f"total: documents={len(manifest['corpora'])} "
            f"seconds={time.perf_counter() - started:.1f}"
        )
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
