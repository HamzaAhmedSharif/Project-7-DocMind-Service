"""Re-run a subset of service-eval questions and merge them into a run block.

Used when part of a run was contaminated (for example a transient provider
outage answering 503 mid-run): the Master Script failure rule re-runs only the
affected questions and counts them against the budget. The eval database and
its corpus are reused (chunk ids stay stable); a fresh key is created in the
same database. Metrics for the merged run are recomputed from the merged
per-question records and the saved raw answers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run_service_eval as rse  # noqa: E402

from evaluation import scoring  # noqa: E402
from evaluation.ledger import record as ledger_record  # noqa: E402
from evaluation.questions import QUESTIONS  # noqa: E402


def recompute(records: list[dict], raw: dict, invalid_total: int, texts: dict) -> dict:
    by_id = {q["id"]: q for q in QUESTIONS}
    total_found = 0
    abstained = 0
    citations_valid = 0
    answered = 0
    answered_with_citation = 0
    prompt_tokens: list[int] = []
    s4_supported = 0
    s4_denominator = 0
    for record_q in records:
        question = by_id[record_q["id"]]
        answer = raw.get(record_q["id"], "")
        citations_valid += len(record_q["citations"])
        if not record_q["refused"]:
            answered += 1
            prompt_tokens.append(record_q["prompt_tokens"])
            if record_q["citations"]:
                answered_with_citation += 1
        if question["type"] == "doc":
            scored = scoring.score_key_facts(answer, question["key_facts"])
            total_found += scored["found"]
            found_facts = [
                kf for kf, hit in zip(question["key_facts"], scored["hits"], strict=True) if hit
            ]
            if found_facts:
                s4_denominator += 1
                cited_text = [texts.get(cid, "") for cid in record_q["citations"]]
                if any(
                    re.search(kf["paper_regex"], scoring.clean(text), re.IGNORECASE)
                    for kf in found_facts
                    for text in cited_text
                ):
                    s4_supported += 1
        else:
            if record_q["refused"] or scoring.is_abstention(answer):
                abstained += 1
    total_citations = citations_valid + invalid_total
    s5_mean = (sum(prompt_tokens) / len(prompt_tokens)) if prompt_tokens else 0.0
    return {
        "s1_key_facts_found": total_found,
        "s2_absent_abstained": abstained,
        "s3_valid_citation_share": (citations_valid / total_citations) if total_citations else 1.0,
        "s3_answers_with_citation_share": (
            (answered_with_citation / answered) if answered else 0.0
        ),
        "s4_citation_supports_fact_share": (
            (s4_supported / s4_denominator) if s4_denominator else 0.0
        ),
        "s5_mean_prompt_tokens": s5_mean,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--image", default="docmind-service:m8")
    args = parser.parse_args(argv)
    rse.current_image = args.image
    wanted = [part.strip() for part in args.questions.split(",") if part.strip()]
    by_id = {q["id"]: q for q in QUESTIONS}
    results = json.loads(rse.RESULTS_PATH.read_text(encoding="utf-8"))
    raw_all = json.loads(rse.RAW_PATH.read_text(encoding="utf-8"))
    run_block = results["runs"][args.run]
    config = rse.RUN_CONFIGS[args.run]

    rse.start_container(config["guardrails"])
    key = rse.create_key()
    invalid_before = rse.invalid_citations()
    new_records: dict[str, dict] = {}
    provider_requests = 0
    try:
        for qid in wanted:
            question = by_id[qid]
            status, payload = rse.http_json(
                "POST",
                "/v1/query",
                {"question": question["question"], "top_k": 10, "mode": "single"},
                {"X-API-Key": key, "Cache-Control": "no-cache"},
                timeout=900,
            )
            answer = payload.get("answer") or ""
            usage = payload.get("usage") or {}
            calls = int(usage.get("calls") or 0)
            provider_requests += calls
            citations = payload.get("citations") or []
            record_q = {
                "id": qid,
                "status": status,
                "refused": bool(payload.get("refused")),
                "refusal_reason": payload.get("refusal_reason"),
                "citations": [c.get("chunk_id") for c in citations if c.get("chunk_id")],
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "api_seconds": usage.get("api_seconds"),
                "wait_seconds": usage.get("wait_seconds"),
                "calls": calls,
            }
            if question["type"] == "doc":
                scored = scoring.score_key_facts(answer, question["key_facts"])
                record_q["facts_found"] = scored["found"]
                record_q["facts_total"] = scored["total"]
            else:
                record_q["abstained"] = bool(payload.get("refused")) or scoring.is_abstention(
                    answer
                )
            new_records[qid] = record_q
            raw_all[args.run][qid] = answer
            print(f"rerun {qid}: status={status} refused={record_q['refused']} calls={calls}")
    finally:
        invalid_after = rse.invalid_citations()
        rse.docker("rm", "-f", rse.CONTAINER)

    merged = []
    for record_q in run_block["questions"]:
        merged.append(new_records.get(record_q["id"], record_q))
    invalid_total = run_block["invalid_citations_delta"] + int(invalid_after - invalid_before)
    all_cited = sorted({cid for record_q in merged for cid in record_q["citations"]})
    texts = rse.chunk_texts(all_cited)
    run_block["questions"] = merged
    run_block["metrics"] = recompute(merged, raw_all[args.run], invalid_total, texts)
    run_block["invalid_citations_delta"] = invalid_total
    run_block["provider_requests"] += provider_requests
    run_block.setdefault("repairs", []).append(
        {
            "questions": wanted,
            "provider_requests": provider_requests,
            "reason": "transient provider 503s in the original run",
        }
    )
    results["runs"][args.run] = run_block
    if args.run == "A":
        results["metrics"] = run_block["metrics"]
    results["provider_requests"] = sum(r["provider_requests"] for r in results["runs"].values())
    rse.RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    rse.RAW_PATH.write_text(json.dumps(raw_all, indent=2) + "\n", encoding="utf-8")
    ledger_record(f"service_eval_{args.run}_repair", provider_requests)
    print(f"merged run {args.run}: {json.dumps(run_block['metrics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
