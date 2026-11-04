"""Embed the sample questions, query the live database, print top-3 pages and scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docmind_service.config import Settings  # noqa: E402
from docmind_service.db import load_dotenv, make_pool  # noqa: E402
from docmind_service.embedding import OnnxEmbedder  # noqa: E402
from docmind_service.store import PgStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the demo questions against the database.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--tenant", default="public")
    parser.add_argument("--questions", default="evaluation/demo_questions.json")
    parser.add_argument("--out", default="evaluation/results/demo-questions-check.json")
    args = parser.parse_args(argv)

    load_dotenv(args.env_file) if args.env_file else load_dotenv(ROOT / ".env")
    settings = Settings(_env_file=None)
    dsn = settings.database_url_value
    if not dsn:
        print("DOCMIND_DATABASE_URL is not set", file=sys.stderr)
        return 2

    questions = json.loads((ROOT / args.questions).read_text(encoding="utf-8"))["questions"]
    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        store = PgStore(
            pool, OnnxEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir)
        )
        titles = {
            record.document_id: record.filename
            for record in store.list_documents(tenant_id=args.tenant)
        }
        results = []
        for item in questions:
            chunks = store.retrieve(
                item["question"], tenant_id=args.tenant, document_ids=None, top_k=3
            )
            top3 = [
                {
                    "document": titles.get(chunk.document_id, str(chunk.document_id)),
                    "page": chunk.page,
                    "score": round(chunk.score, 4),
                }
                for chunk in chunks
            ]
            results.append({"id": item["id"], "question": item["question"], "top3": top3})
            print(
                f"{item['id']}: "
                + " | ".join(f"{row['document']} p{row['page']} {row['score']:.4f}" for row in top3)
            )
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"tenant": args.tenant, "questions": results}, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
