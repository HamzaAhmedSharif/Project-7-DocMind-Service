"""Evidence-threshold calibration (M6.4): retrieval only, no provider calls."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from docmind_service.config import Settings
from docmind_service.db import make_pool, migrate
from docmind_service.embedding import OnnxEmbedder
from docmind_service.ingest import prepare_document
from docmind_service.store import PgStore
from evaluation.questions import QUESTIONS
from scripts.fetch_corpus import fetch

ROOT = Path(__file__).resolve().parents[1]
PAPER_MANIFEST = ROOT / "evaluation" / "corpus.json"
DEMO_MANIFEST = ROOT / "evaluation" / "demo_corpus.json"
DEMO_QUESTIONS = ROOT / "evaluation" / "demo_questions.json"
DEMO_OFFTOPIC = ROOT / "evaluation" / "demo_offtopic.json"


def threshold_from(scores: list[float]) -> float:
    """Pre-declared rule: floor_to_2_decimals(min answerable top-1 - 0.02)."""
    if not scores:
        raise ValueError("at least one answerable score is required")
    return max(0.0, math.floor(round((min(scores) - 0.02) * 100, 9)) / 100)


def _top1(store: PgStore, question: str, tenant: str) -> dict:
    hits = store.retrieve(question, tenant_id=tenant, document_ids=None, top_k=1)
    if not hits:
        return {"score": 0.0, "chunk_id": None, "page": None}
    hit = hits[0]
    return {"score": round(hit.score, 6), "chunk_id": hit.chunk_id, "page": hit.page}


def ingest_paper(pool, embedder: OnnxEmbedder, tenant: str = "evidence-paper") -> int:
    manifest = json.loads(PAPER_MANIFEST.read_text(encoding="utf-8"))
    corpus = manifest["corpora"][0]
    path = ROOT / "data" / "cache" / f"{corpus['id']}.pdf"
    fetch(corpus["url"], path, corpus["sha256"])
    prepared = prepare_document(path.read_bytes(), f"{corpus['id']}.pdf", max_pages=200)
    embeddings = embedder.embed_passages([chunk.text for chunk in prepared.chunks])
    store = PgStore(pool, embedder)
    with pool.connection(timeout=3) as conn:
        conn.execute("DELETE FROM documents WHERE tenant_id = %s", (tenant,))
    store.add_document(
        tenant_id=tenant,
        sha256=prepared.sha256,
        filename=f"{corpus['id']}.pdf",
        pages=len(prepared.pages),
        chunks=prepared.chunks,
        embeddings=embeddings,
    )
    return len(prepared.chunks)


def ingest_demo(pool, embedder: OnnxEmbedder, tenant: str = "evidence-demo") -> int:
    manifest = json.loads(DEMO_MANIFEST.read_text(encoding="utf-8"))
    store = PgStore(pool, embedder)
    with pool.connection(timeout=3) as conn:
        conn.execute("DELETE FROM documents WHERE tenant_id = %s", (tenant,))
    total = 0
    for item in manifest["corpora"]:
        path = ROOT / "data" / "demo" / f"{item['id']}.pdf"
        fetch(item["url"], path, item["sha256"])
        prepared = prepare_document(path.read_bytes(), f"{item['id']}.pdf", max_pages=200)
        embeddings = embedder.embed_passages([chunk.text for chunk in prepared.chunks])
        store.add_document(
            tenant_id=tenant,
            sha256=prepared.sha256,
            filename=item["title"],
            pages=len(prepared.pages),
            chunks=prepared.chunks,
            embeddings=embeddings,
        )
        total += len(prepared.chunks)
    return total


def _paper_rows(store: PgStore, tenant: str) -> list[dict]:
    rows = []
    for question in QUESTIONS:
        if question["type"] not in {"doc", "absent"}:
            continue
        top = _top1(store, question["question"], tenant)
        rows.append(
            {
                "id": question["id"],
                "type": question["type"],
                "question": question["question"],
                "top1_score": top["score"],
                "top1_chunk_id": top["chunk_id"],
                "top1_page": top["page"],
            }
        )
    return rows


def _demo_rows(store: PgStore, tenant: str) -> list[dict]:
    rows = []
    questions = json.loads(DEMO_QUESTIONS.read_text(encoding="utf-8"))["questions"]
    offtopic = json.loads(DEMO_OFFTOPIC.read_text(encoding="utf-8"))["questions"]
    for item in questions:
        top = _top1(store, item["question"], tenant)
        rows.append(
            {
                "id": item["id"],
                "type": "answerable",
                "question": item["question"],
                "top1_score": top["score"],
                "top1_chunk_id": top["chunk_id"],
                "top1_page": top["page"],
            }
        )
    for item in offtopic:
        top = _top1(store, item["question"], tenant)
        rows.append(
            {
                "id": item["id"],
                "type": "offtopic",
                "question": item["question"],
                "top1_score": top["score"],
                "top1_chunk_id": top["chunk_id"],
                "top1_page": top["page"],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--corpus", choices=["attention", "demo"], default="attention")
    args = parser.parse_args(argv)
    dsn = os.environ.get("DOCMIND_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("DOCMIND_TEST_DATABASE_URL is not set")
    if not dsn.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        raise SystemExit("DOCMIND_TEST_DATABASE_URL must name a database ending in _test")

    settings = Settings(_env_file=None)
    migrate(dsn)
    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        embedder = OnnxEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir)
        if args.corpus == "attention":
            tenant = "evidence-paper"
            n_chunks = ingest_paper(pool, embedder, tenant)
            rows = _paper_rows(PgStore(pool, embedder), tenant)
            answerable = [row for row in rows if row["type"] == "doc"]
            absent = [row for row in rows if row["type"] == "absent"]
        else:
            tenant = "evidence-demo"
            n_chunks = ingest_demo(pool, embedder, tenant)
            rows = _demo_rows(PgStore(pool, embedder), tenant)
            answerable = [row for row in rows if row["type"] == "answerable"]
            absent = [row for row in rows if row["type"] == "offtopic"]
        threshold = threshold_from([row["top1_score"] for row in answerable])
        below = [row["id"] for row in absent if row["top1_score"] < threshold]
        result = {
            "corpus": args.corpus,
            "generated_at": datetime.now(UTC).isoformat(),
            "tenant": tenant,
            "n_chunks": n_chunks,
            "rule": "t = floor_to_2_decimals(min(top-1 of answerable) - 0.02)",
            "questions": rows,
            "min_answerable_top1": min(row["top1_score"] for row in answerable),
            "threshold": threshold,
            "absent_total": len(absent),
            "absent_below_threshold": len(below),
            "absent_below_ids": below,
            "provider_requests": 0,
        }
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"corpus={args.corpus} chunks={n_chunks}")
        for row in rows:
            print(f"{row['id']} {row['type']} top1={row['top1_score']:.4f}")
        print(f"threshold={threshold:.2f} absent_below={len(below)}/{len(absent)} ids={below}")
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
