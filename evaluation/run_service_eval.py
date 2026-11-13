"""Service-level evaluation (Master Script 10.2) - gates S1 to S5.

Runs the shipped Docker image against a throwaway local database (docmind_eval)
with the real provider, through the HTTP API only. Scores with the copied
Project 6 scorer. Writes evaluation/results/service-eval-m8.json (metrics of
run A at the top level; every run under "runs") and the raw answers to the
git-ignored reports/service-eval-raw.json. The eval database is recreated on
every invocation; the svc-eval key exists only in this process's memory.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation import scoring  # noqa: E402
from evaluation.ledger import record as ledger_record  # noqa: E402
from evaluation.questions import QUESTIONS  # noqa: E402

BASE = "http://127.0.0.1:8010"
CONTAINER = "docmind-eval"
ADMIN_DSN = "postgresql://postgres@127.0.0.1:5433/postgres"
EVAL_DSN_HOST = "postgresql://postgres@127.0.0.1:5433/docmind_eval"
EVAL_DSN_CONTAINER = "postgresql://postgres@host.docker.internal:5433/docmind_eval"
RESULTS_PATH = ROOT / "evaluation" / "results" / "service-eval-m8.json"
RAW_PATH = ROOT / "reports" / "service-eval-raw.json"
MODEL = "openai/gpt-oss-120b"
PAPER_THRESHOLD = 0.35

RUN_CONFIGS = {
    "A": {"guardrails": True},
    "B": {"guardrails": True},
    "C": {"guardrails": False},
    # P7.1 remediation re-runs (post-hoc iteration; same configuration as A/B).
    "A2": {"guardrails": True},
    "B2": {"guardrails": True},
    # P7.2 re-runs (post-hoc iteration; prompt p7-v3, quote-anchored repair).
    "A3": {"guardrails": True, "prompt_version": "p7-v3"},
    "B3": {"guardrails": True, "prompt_version": "p7-v3"},
    # P7.3 re-runs (post-hoc iteration; retrieval unfrozen — cross-encoder
    # reranker in the p73 image; same prompt p7-v3, guardrails on).
    "A4": {"guardrails": True, "prompt_version": "p7-v3"},
    "B4": {"guardrails": True, "prompt_version": "p7-v3"},
}


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=300)


def http(method: str, path: str, body: bytes | None, headers: dict, timeout: float = 60.0):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        return 0, str(exc).encode()


def http_json(method: str, path: str, payload: dict | None, headers: dict, timeout: float = 60.0):
    body = json.dumps(payload).encode() if payload is not None else None
    merged = {"Content-Type": "application/json", **headers}
    status, raw = http(method, path, body, merged, timeout)
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return status, {}


def multipart(filename: str, data: bytes):
    boundary = "----docmind" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    return (
        head + data + f"\r\n--{boundary}--\r\n".encode(),
        f"multipart/form-data; boundary={boundary}",
    )


def invalid_citations() -> float:
    _, raw = http("GET", "/metrics", None, {}, timeout=30)
    pattern = r'docmind_guardrail_total\{kind="invalid_citation"\}\s+([0-9.]+)'
    match = re.search(pattern, raw.decode())
    return float(match.group(1)) if match else 0.0


def wait_readyz(timeout_s: float = 240.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, _ = http("GET", "/readyz", None, {}, timeout=10)
        if status == 200:
            return
        time.sleep(3)
    logs = docker("logs", "--tail", "40", CONTAINER)
    raise SystemExit(f"container never became ready:\n{logs.stdout}\n{logs.stderr}")


def start_container(guardrails: bool) -> None:
    assert "host.docker.internal" in EVAL_DSN_CONTAINER and "neon" not in EVAL_DSN_CONTAINER
    docker("rm", "-f", CONTAINER)
    args = [
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-m",
        "512m",
        "--env-file",
        str(ROOT / ".env"),
        "-e",
        f"DOCMIND_DATABASE_URL={EVAL_DSN_CONTAINER}",
        "-e",
        "DOCMIND_AUTO_MIGRATE=true",
        "-e",
        "DOCMIND_LLM_PROVIDER=hosted",
        "-e",
        "DOCMIND_CACHE_ENABLED=false",
        "-p",
        "8010:8000",
    ]
    if guardrails:
        args += [
            "-e",
            f"DOCMIND_EVIDENCE_MIN_SCORE={PAPER_THRESHOLD}",
            "-e",
            "DOCMIND_REQUIRE_CITATION=true",
        ]
    else:
        args += ["-e", "DOCMIND_GUARDRAILS_ENABLED=false"]
    args.append(current_image)
    result = docker(*args)
    if result.returncode != 0:
        raise SystemExit(f"docker run failed: {result.stderr}")
    wait_readyz()


def fresh_database() -> None:
    docker("rm", "-f", CONTAINER)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'docmind_eval' AND pid <> pg_backend_pid()"
        )
        conn.execute("DROP DATABASE IF EXISTS docmind_eval")
        conn.execute("CREATE DATABASE docmind_eval")


def create_key() -> str:
    from docmind_service.auth import PgAuthStore
    from docmind_service.db import make_pool

    pool = make_pool(EVAL_DSN_HOST)
    pool.open(wait=True)
    try:
        _, full_key = PgAuthStore(pool).create(
            tenant_id="svc-eval",
            label="m8-service-eval",
            scopes=["read", "write"],
            rpm=1000,
            daily_queries=100000,
            max_documents=10,
            max_pages=1000,
        )
        return full_key
    finally:
        pool.close()


def ensure_corpus() -> Path:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "fetch_corpus.py"),
            "--manifest",
            str(ROOT / "evaluation" / "corpus.json"),
            "--out",
            str(ROOT / "evaluation" / "corpus"),
        ],
        check=True,
        timeout=600,
    )
    return ROOT / "evaluation" / "corpus" / "attention.pdf"


def upload_paper(key: str, pdf: Path) -> dict:
    body, ctype = multipart(pdf.name, pdf.read_bytes())
    status, raw = http(
        "POST",
        "/v1/documents",
        body,
        {"Content-Type": ctype, "X-API-Key": key},
        timeout=900,
    )
    doc = json.loads(raw.decode("utf-8", "replace"))
    if status not in (200, 201):
        raise SystemExit(f"upload failed: status={status} body={str(doc)[:200]}")
    return doc


def chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    with psycopg.connect(EVAL_DSN_HOST) as conn:
        rows = conn.execute(
            "SELECT chunk_id, text FROM chunks WHERE chunk_id = ANY(%s)", (chunk_ids,)
        ).fetchall()
    return {chunk_id: text for chunk_id, text in rows}


def run_once(name: str, key: str) -> tuple[dict, dict]:
    config = RUN_CONFIGS[name]
    start_container(config["guardrails"])
    invalid_before = invalid_citations()
    answerable = [q for q in QUESTIONS if q["type"] == "doc"]
    absent = [q for q in QUESTIONS if q["type"] == "absent"]
    per_question: list[dict] = []
    raw_answers: dict[str, str] = {}
    provider_requests = 0
    total_found = 0
    all_found_questions = 0
    abstained = 0
    citations_valid = 0
    answered = 0
    answered_with_citation = 0
    prompt_tokens: list[int] = []
    s4_supported = 0
    s4_denominator = 0
    cited_ids: list[str] = []
    fact_hits: dict[str, list[bool]] = {}

    for question in answerable + absent:
        status, payload = http_json(
            "POST",
            "/v1/query",
            {"question": question["question"], "top_k": 10, "mode": "single"},
            {"X-API-Key": key, "Cache-Control": "no-cache"},
            timeout=900,
        )
        answer = payload.get("answer") or ""
        refused = bool(payload.get("refused"))
        usage = payload.get("usage") or {}
        calls = int(usage.get("calls") or 0)
        provider_requests += calls
        citations = payload.get("citations") or []
        citation_ids = [c.get("chunk_id") for c in citations if c.get("chunk_id")]
        record_q = {
            "id": question["id"],
            "status": status,
            "refused": refused,
            "refusal_reason": payload.get("refusal_reason"),
            "citations": citation_ids,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "api_seconds": usage.get("api_seconds"),
            "wait_seconds": usage.get("wait_seconds"),
            "calls": calls,
        }
        raw_answers[question["id"]] = answer
        if not refused:
            answered += 1
            prompt_tokens.append(record_q["prompt_tokens"])
            if citation_ids:
                answered_with_citation += 1
        citations_valid += len(citation_ids)
        cited_ids.extend(citation_ids)
        if question["type"] == "doc":
            scored = scoring.score_key_facts(answer, question["key_facts"])
            record_q["facts_found"] = scored["found"]
            record_q["facts_total"] = scored["total"]
            total_found += scored["found"]
            fact_hits[question["id"]] = scored["hits"]
            if scored["all_found"]:
                all_found_questions += 1
        else:
            is_abs = refused or scoring.is_abstention(answer)
            record_q["abstained"] = is_abs
            if is_abs:
                abstained += 1
        per_question.append(record_q)

    texts = chunk_texts(sorted(set(cited_ids)))
    by_id = {q["id"]: q for q in QUESTIONS}
    for record_q in per_question:
        question = by_id[record_q["id"]]
        if question["type"] != "doc":
            continue
        hits = fact_hits[record_q["id"]]
        found_facts = [kf for kf, hit in zip(question["key_facts"], hits, strict=True) if hit]
        if not found_facts:
            continue
        s4_denominator += 1
        cited_text = [texts.get(cid, "") for cid in record_q["citations"]]
        supported = any(
            re.search(kf["paper_regex"], scoring.clean(text), re.IGNORECASE)
            for kf in found_facts
            for text in cited_text
        )
        if supported:
            s4_supported += 1

    invalid_delta = invalid_citations() - invalid_before
    total_citations = citations_valid + int(invalid_delta)
    s3_valid = (citations_valid / total_citations) if total_citations else 1.0
    s3_answers = (answered_with_citation / answered) if answered else 0.0
    s4_share = (s4_supported / s4_denominator) if s4_denominator else 0.0
    s5_mean = (sum(prompt_tokens) / len(prompt_tokens)) if prompt_tokens else 0.0
    metrics = {
        "s1_key_facts_found": total_found,
        "s2_absent_abstained": abstained,
        "s3_valid_citation_share": s3_valid,
        "s3_answers_with_citation_share": s3_answers,
        "s4_citation_supports_fact_share": s4_share,
        "s5_mean_prompt_tokens": s5_mean,
    }
    run_block = {
        "config": {
            "guardrails": config["guardrails"],
            "prompt_version": config.get("prompt_version")
            or ("p7-v2" if config["guardrails"] else "p7-v1"),
            "evidence_min_score": PAPER_THRESHOLD if config["guardrails"] else "guardrails-off",
            "require_citation": config["guardrails"],
            "cache_enabled": False,
        },
        "metrics": metrics,
        "all_facts_questions": all_found_questions,
        "provider_requests": provider_requests,
        "invalid_citations_delta": int(invalid_delta),
        "questions": per_question,
    }
    ledger_record(f"service_eval_{name}", provider_requests)
    return run_block, raw_answers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="A")
    parser.add_argument("--image", default="docmind-service:m8")
    parser.add_argument("--results", default=None)
    args = parser.parse_args(argv)
    results_path = Path(args.results) if args.results else RESULTS_PATH
    global current_image
    current_image = args.image
    names = [part.strip().upper() for part in args.runs.split(",") if part.strip()]
    for name in names:
        if name not in RUN_CONFIGS:
            raise SystemExit(f"unknown run {name}")

    pdf = ensure_corpus()
    fresh_database()
    # The first container start runs the migrations; the key needs the tables.
    start_container(RUN_CONFIGS[names[0]]["guardrails"])
    key = create_key()
    doc = upload_paper(key, pdf)
    print(f"uploaded document chunks={doc.get('chunks')} pages={doc.get('pages')}")

    results = {}
    if results_path.is_file():
        results = json.loads(results_path.read_text(encoding="utf-8"))
    raw_all = {}
    if RAW_PATH.is_file():
        raw_all = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    runs = results.get("runs", {})
    try:
        for name in names:
            run_block, raw_answers = run_once(name, key)
            runs[name] = run_block
            raw_all[name] = raw_answers
            print(
                f"run {name}: {json.dumps(run_block['metrics'])} "
                f"provider_requests={run_block['provider_requests']}"
            )
    finally:
        docker("rm", "-f", CONTAINER)

    results["runs"] = runs
    if "A" in runs:
        results["metrics"] = runs["A"]["metrics"]
    results["provider_requests"] = sum(r["provider_requests"] for r in runs.values())
    results["config"] = {
        "image": current_image,
        "model": MODEL,
        "corpus": "attention (arXiv 1706.03762v7)",
        "questions": "d01-d12 answerable (26 facts), a01-a04 absent; web out of scope",
        "database": "local docmind_eval in the pgvector container",
    }
    results_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(json.dumps(raw_all, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {results_path.name}; ledger used_today follows")
    return 0


current_image = "docmind-service:m8"

if __name__ == "__main__":
    sys.exit(main())
