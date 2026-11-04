#!/usr/bin/env python3
"""Simple load-test client for DocMind service (M7.3).

Usage:
    python scripts/loadtest.py --base http://127.0.0.1:8001 \
        --concurrency 10 \
        --duration 60 \
        --scenario mixed \
        --out results/load-m7.json

The script sends POST /v1/query requests from a small question set until
the duration is exceeded, using a pool of worker threads.

The output JSON includes: overall request counts, RPS, latency
percentiles, status-code counts, timeout counts, and a simple
API-response-summary.
"""

import argparse
import json
import os
import random
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

# Demo questions used for answered scenario – these are small, real questions.
ANSWERED_QUESTIONS = [
    "What is the safety of autonomous cars?",
    "Explain the concept of reinforcement learning.",
    "What is the difference between LLM and GPT?",
    "Describe the generational gap in tech.",
    "What are the core principles of data privacy?",
    "Explain the concept of zero‑knowledge proof.",
]

# Random unmatchable strings – used for refused scenario.
REFUSED_WORDS = ["zxqv", "qwerty", "asdfgh", "zxc", "loremip"]


def make_questions(scenario: str, count: int = 50) -> list[str]:
    """Return a list of questions according to the chosen scenario.

    1. answered - pick from ANSWERED_QUESTIONS.
    2. refused - random words.
    3. mixed - 80% answered, 20% refused.
    """
    if scenario == "answered":
        return [random.choice(ANSWERED_QUESTIONS) for _ in range(count)]
    if scenario == "refused":
        return [random.choice(REFUSED_WORDS) + " " + os.urandom(3).hex() for _ in range(count)]
    # mixed
    answered = [random.choice(ANSWERED_QUESTIONS) for _ in range(int(count * 0.8))]
    refused = [
        random.choice(REFUSED_WORDS) + " " + os.urandom(3).hex()
        for _ in range(count - len(answered))
    ]
    random.shuffle(answered + refused)
    return answered + refused


def do_request(base: str, question: str):
    url = f"{base.rstrip('/')}/v1/query"
    data = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        start = time.time()
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
        latency = time.time() - start
        return resp.status, latency, body
    except urllib.error.HTTPError as exc:
        latency = time.time() - start
        return exc.code, latency, str(exc)
    except Exception as exc:
        latency = time.time() - start
        return None, latency, str(exc)


def main():
    parser = argparse.ArgumentParser(description="DocMind load tester")
    parser.add_argument(
        "--base", required=True, help="Base URL of the service e.g. http://localhost:8000"
    )
    parser.add_argument("--concurrency", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    parser.add_argument(
        "--scenario",
        choices=["answered", "refused", "mixed"],
        default="mixed",
        help="Request scenario",
    )
    parser.add_argument("--out", default="results/load-m7.json", help="Path to write JSON output")
    args = parser.parse_args()

    questions = make_questions(args.scenario, 200)
    total_requests = 0
    latency_samples = []
    status_counts = {}
    timeouts = 0

    start_time = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        pending = set()
        idx = 0
        while pending or (time.time() - start_time) < args.duration:
            while len(pending) < args.concurrency and (
                time.time() - start_time
            ) < args.duration:
                pending.add(
                    executor.submit(
                        do_request, args.base, questions[idx % len(questions)]
                    )
                )
                idx += 1
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                status, lat, _ = future.result()
                if status is None:
                    timeouts += 1
                else:
                    status_counts[status] = status_counts.get(status, 0) + 1
                latency_samples.append(lat)
                total_requests += 1
    elapsed = time.time() - start_time
    rps = total_requests / elapsed if elapsed > 0 else 0
    result = {
        "requests": total_requests,
        "duration_seconds": elapsed,
        "rps": rps,
        "p50": statistics.median(latency_samples) if latency_samples else 0,
        "p95": statistics.quantiles(latency_samples, n=20)[-1] if latency_samples else 0,
        "p99": statistics.quantiles(latency_samples, n=100)[-1] if latency_samples else 0,
        "status_counts": status_counts,
        "timeouts": timeouts,
    }
    if args.out == "-":
        print(json.dumps(result, indent=2))
    else:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("Results written to", args.out)


if __name__ == "__main__":
    main()
