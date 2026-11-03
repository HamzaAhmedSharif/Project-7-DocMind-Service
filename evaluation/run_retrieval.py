import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from pypdf import __version__ as pypdf_version

from docmind_service.chunking import chunk_pages
from docmind_service.config import get_settings
from docmind_service.db import make_pool, migrate
from docmind_service.embedding import OnnxEmbedder
from docmind_service.ingest import extract_pages
from docmind_service.store import PgStore
from evaluation.questions import QUESTIONS
from evaluation.scoring import score_key_facts
from scripts.fetch_corpus import fetch

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "corpus.json"
FIXTURES = ROOT / "evaluation" / "fixtures"


def _cosine_rows(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    numerator = np.sum(a * b, axis=1)
    denominator = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    return numerator / np.maximum(denominator, 1e-12)


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _metadata(pool) -> dict:
    with pool.connection() as conn:
        extension = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        server = conn.execute("SHOW server_version").fetchone()[0]
        chunk_size = conn.execute("SELECT pg_total_relation_size('chunks')").fetchone()[0]
    import fastembed
    import onnxruntime
    import psycopg as psycopg_module

    return {
        "python": platform.python_version(),
        "fastembed": getattr(fastembed, "__version__", "unknown"),
        "onnxruntime": getattr(onnxruntime, "__version__", "unknown"),
        "pypdf": pypdf_version,
        "psycopg": getattr(psycopg_module, "__version__", "unknown"),
        "pgvector": extension[0] if extension else None,
        "postgres": server,
        "git_commit": _git_commit(),
        "chunks_table_bytes": chunk_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="local")
    args = parser.parse_args(argv)
    dsn = os.environ.get("DOCMIND_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("DOCMIND_TEST_DATABASE_URL is not set")
    if not dsn.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        raise SystemExit("DOCMIND_TEST_DATABASE_URL must name a database ending in _test")
    top_k = get_settings().default_top_k

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    corpus = manifest["corpora"][0]
    corpus_path = ROOT / "data" / "cache" / f"{corpus['id']}.pdf"
    fetch(corpus["url"], corpus_path, corpus["sha256"])
    prepared_started = time.perf_counter()
    pages = extract_pages(corpus_path.read_bytes(), max_pages=corpus["pages"])
    chunks = chunk_pages(pages)
    prepare_seconds = time.perf_counter() - prepared_started
    (ROOT / "data" / "work").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "work" / "chunks.json").write_text(
        json.dumps([{"ordinal": c.ordinal, "page": c.page, "text": c.text} for c in chunks]),
        encoding="utf-8",
    )

    migrate(dsn)
    pool = make_pool(dsn)
    pool.open(wait=True)
    embedder = OnnxEmbedder(cache_dir=os.environ.get("DOCMIND_MODEL_CACHE_DIR"))
    store = PgStore(pool, embedder)
    try:
        with pool.connection() as conn:
            conn.execute("DELETE FROM documents WHERE tenant_id = %s", ("eval",))
        ingest_started = time.perf_counter()
        embeddings = embedder.embed_passages([c.text for c in chunks])
        store.add_document(
            tenant_id="eval",
            sha256=corpus["sha256"],
            filename=corpus["id"] + ".pdf",
            pages=len(pages),
            chunks=chunks,
            embeddings=embeddings,
        )
        ingest_seconds = time.perf_counter() - ingest_started

        reference_chunks = np.load(FIXTURES / "reference_chunk_vectors.npy")
        reference_questions = np.load(FIXTURES / "reference_question_vectors.npy")
        question_vectors = embedder.embed_passages([q["question"] for q in QUESTIONS])
        # Positional chunk comparison only makes sense for the reference chunking;
        # a changed chunk count is reported as unavailable (E1 question parity still applies).
        chunk_cos = (
            _cosine_rows(embeddings, reference_chunks)
            if embeddings.shape[0] == reference_chunks.shape[0]
            else None
        )
        question_cos = _cosine_rows(question_vectors, reference_questions)
        all_cos = question_cos if chunk_cos is None else np.concatenate([chunk_cos, question_cos])

        top10 = json.loads((FIXTURES / "reference_top10.json").read_text(encoding="utf-8"))
        e2 = {}
        e3 = {"found": 0, "total": 0, "missed": []}
        for question in QUESTIONS:
            embedder.clear_cache()
            hits = store.retrieve(
                question["question"],
                tenant_id="eval",
                document_ids=None,
                top_k=top_k,
            )
            ordinals = [int(hit.chunk_id.rsplit(":", 1)[1]) for hit in hits]
            e2[question["id"]] = len(set(ordinals) & set(top10[question["id"]])) / 10
            if question["type"] == "doc":
                context = "\n".join(hit.text for hit in hits)
                scored = score_key_facts(context, question["key_facts"])
                e3["found"] += scored["found"]
                e3["total"] += scored["total"]
                for fact, hit in zip(question["key_facts"], scored["hits"], strict=True):
                    if not hit:
                        e3["missed"].append({"id": question["id"], "fact": fact["fact"]})

        latencies = []
        for _ in range(5):
            for question in QUESTIONS:
                embedder.clear_cache()
                started = time.perf_counter()
                store.retrieve(
                    question["question"],
                    tenant_id="eval",
                    document_ids=None,
                    top_k=top_k,
                )
                latencies.append(time.perf_counter() - started)
        latency = {
            "samples": len(latencies),
            "p50_seconds": float(np.percentile(latencies, 50)),
            "p95_seconds": float(np.percentile(latencies, 95)),
        }
        metadata = _metadata(pool)
        result = {
            "label": args.label,
            "stage": "retrieval",
            "generated_at": datetime.now(UTC).isoformat(),
            "corpus": corpus,
            "n_chunks": len(chunks),
            "top_k": top_k,
            "prepare_seconds": prepare_seconds,
            "ingest_seconds": ingest_seconds,
            "e1": {
                "min_cosine": float(all_cos.min()),
                "mean_cosine": float(all_cos.mean()),
                "chunk_min_cosine": None if chunk_cos is None else float(chunk_cos.min()),
                "question_min_cosine": float(question_cos.min()),
            },
            "e2": {
                "mean_top10_overlap": float(np.mean(list(e2.values()))),
                "per_question": e2,
            },
            "e3": e3,
            "latency": latency,
            "metadata": metadata,
            "metrics": {
                "e1_min_cosine": float(all_cos.min()),
                "e1_mean_cosine": float(all_cos.mean()),
                "e2_mean_top10_overlap": float(np.mean(list(e2.values()))),
                "e3_key_facts_found": e3["found"],
            },
        }
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            f"E1 min={result['e1']['min_cosine']:.6f} mean={result['e1']['mean_cosine']:.6f} "
            f"E2={result['e2']['mean_top10_overlap']:.3f} "
            f"E3={e3['found']}/{e3['total']} chunks={len(chunks)}"
        )
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
