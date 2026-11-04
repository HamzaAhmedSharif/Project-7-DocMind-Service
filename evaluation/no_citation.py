"""No-citation policy measurement (M6.4): 12 answerable paper questions, policy off."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

from docmind_service.config import Settings
from docmind_service.db import load_local_env, make_pool, migrate
from docmind_service.embedding import OnnxEmbedder
from docmind_service.guardrails import PROMPT_VERSION
from docmind_service.llm import STATS, HostedLLM
from docmind_service.query import answer_question
from docmind_service.store import PgStore
from evaluation.calibrate_evidence import ingest_paper
from evaluation.questions import QUESTIONS

ROOT = Path(__file__).resolve().parents[1]


def summarize(rows: list[dict]) -> dict:
    no_citation = sum(1 for row in rows if not row["refused"] and not row["citations"])
    return {
        "total": len(rows),
        "no_citation": no_citation,
        "recommended_default": no_citation <= 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(ROOT / "evaluation" / "results" / "no-citation-m6.json"),
    )
    args = parser.parse_args(argv)
    dsn = os.environ.get("DOCMIND_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("DOCMIND_TEST_DATABASE_URL is not set")
    if not dsn.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        raise SystemExit("DOCMIND_TEST_DATABASE_URL must name a database ending in _test")

    load_local_env()
    settings = Settings(_env_file=None, llm_provider="hosted")
    pending = not settings.llm_api_key_value
    if pending:
        print("PENDING-H6")
        result = {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "PENDING-H6",
            "total": 0,
            "no_citation": None,
            "recommended_default": None,
            "answers": [],
            "provider_requests": 0,
        }
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0

    migrate(dsn)
    pool = make_pool(dsn)
    pool.open(wait=True)
    try:
        embedder = OnnxEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir)
        tenant = "evidence-paper"
        ingest_paper(pool, embedder, tenant)
        store = PgStore(pool, embedder)
        llm = HostedLLM(settings)
        canary = secrets.token_hex(16)
        rows = []
        before_all = STATS["calls"]
        for question in QUESTIONS:
            if question["type"] != "doc":
                continue
            before = STATS["calls"]
            result = answer_question(
                question["question"],
                tenant_id=tenant,
                retriever=store,
                llm=llm,
                document_ids=None,
                top_k=settings.default_top_k,
                guardrails_enabled=True,
                evidence_min_score=settings.evidence_min_score,
                canary=canary,
                require_citation=False,
                max_answer_chars=settings.max_answer_chars,
            )
            used = STATS["calls"] - before
            rows.append(
                {
                    "id": question["id"],
                    "refused": result.refused,
                    "refusal_reason": result.refusal_reason,
                    "citations": len(result.citations),
                    "citation_ids": [citation.chunk_id for citation in result.citations],
                    "answer_chars": len(result.answer),
                    "prompt_tokens": result.llm.prompt_tokens if result.llm else 0,
                    "completion_tokens": result.llm.completion_tokens if result.llm else 0,
                    "provider_requests": used,
                }
            )
            print(
                f"{question['id']} refused={result.refused} "
                f"citations={len(result.citations)} calls={used}"
            )
        summary = summarize(rows)
        result = {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "measured",
            "model": settings.llm_model,
            "prompt_version": PROMPT_VERSION,
            "require_citation_measured": False,
            **summary,
            "answers": rows,
            "provider_requests": STATS["calls"] - before_all,
        }
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            f"no_citation={summary['no_citation']}/{summary['total']} "
            f"recommended_default={summary['recommended_default']} "
            f"provider_requests={result['provider_requests']}"
        )
        print(f"wrote {out}")
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
