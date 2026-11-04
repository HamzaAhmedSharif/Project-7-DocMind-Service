#!/usr/bin/env python3
"""Utility to run the M7 load‑test matrix and create evaluation/results/load-m7.json.

The script:
  1. Starts a docmind‑service container (demo mode, fake LLM provider).
  2. Waits for the health endpoint to become healthy.
  3. In parallel performs:
     * A 60‑second mixed‑scenario load test with 10 concurrent workers.
     * Periodic docker‑stats snapshots to record peak RSS.
  4. After load finishes, retrieves metrics, parses out status counts, counts
     any 5xx responses, and checks if the container OOM‑killed.
  5. Writes a JSON report into evaluation/results/load-m7.json.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from threading import Thread

# Configuration
CONCURRENCY = 10
DURATION = 60
SCENARIO = "mixed"
BASE = "http://127.0.0.1:8002"
CONTAINER_NAME = "docmind-m7"
# Path where output will be written
OUTPUT_PATH = Path("evaluation/results/load-m7.json")

# Helper to run subprocess commands


def run(cmd, env=None, check=True, capture_output=False):
    res = subprocess.run(cmd, env=env, check=check, capture_output=capture_output, text=True)
    return res.stdout if capture_output else None


# Start the container
run(
    [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "-e",
        "DOCMIND_LLM_PROVIDER=fake",
        "-e",
        "DOCMIND_CACHE_ENABLED=false",
        "-e",
        "DOCMIND_AUTO_MIGRATE=true",
        "-e",
        "DOCMIND_DATABASE_URL=postgresql://postgres@host.docker.internal:5433/docmind",
        "-e",
        "DOCMIND_DEMO_IP_PER_MIN=100000",
        "-e",
        "DOCMIND_DEMO_DAILY_CAP=1000000",
        "-e",
        "DOCMIND_GLOBAL_DAILY_LLM_CAP=1000000",
        "--memory",
        "512m",
        "-p",
        "127.0.0.1:8002:8000",
        "docmind-service:m7",
    ]
)


def wait_health():
    for _ in range(30):
        try:
            out = run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{BASE}/healthz"],
                check=False,
                capture_output=True,
            )
            if out.strip() == "200":
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Health endpoint not up")


wait_health()

# Start Docker stats monitoring
peak_mem_mb = 0
running = True


def monitor_stats():
    global peak_mem_mb
    while running:
        try:
            out = run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", CONTAINER_NAME],
                capture_output=True,
            )
            # out example: "168.94MiB / 512MiB"
            m = re.match(r"([\d\.]+)([KMG]iB) \/", out)
            if m:
                value, unit = m.group(1), m.group(2)
                if unit == "GiB":
                    mb = float(value) * 1024
                elif unit == "MiB":
                    mb = float(value)
                elif unit == "KiB":
                    mb = float(value) / 1024
                else:
                    mb = float(value)
                peak_mem_mb = max(peak_mem_mb, mb)
        except Exception:
            pass
        time.sleep(2)


thread = Thread(target=monitor_stats, daemon=True)
thread.start()

# Run load test
load_cmd = [
    "python",
    "scripts/loadtest.py",
    "--base",
    BASE,
    "--concurrency",
    str(CONCURRENCY),
    "--duration",
    str(DURATION),
    "--scenario",
    SCENARIO,
    "--out",
    "-",
]
load_res = subprocess.run(load_cmd, capture_output=True, text=True)
# parse JSON output from stdout
load_report = json.loads(load_res.stdout)
# Retrieve metrics to compute status counts
metrics_txt = run(["curl", "-s", f"{BASE}/metrics"], capture_output=True)
# Check OOM
oom = (
    run(
        ["docker", "inspect", CONTAINER_NAME, "--format", "{{.State.OOMKilled}}"],
        capture_output=True,
    ).strip()
    == "true"
)

# Stop monitoring and container
running = False
thread.join(1)
run(["docker", "rm", "-f", CONTAINER_NAME])

# Parse status counts from docmind_query_total{status="xx"}
status_counts: dict[str, int] = {}
for match in re.finditer(r'docmind_query_total\{.*status="(\d{3})".*\}', metrics_txt):
    # count each occurrence in counter samples
    path = match.group(0)
    value_match = re.search(r'"([0-9\.]+)"', path)


def parse_counter(text):
    # Count responses by status from docmind_http_requests_total for the
    # /v1/query route (docmind_query_total has no status label).
    d: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("docmind_http_requests_total"):
            m = re.match(r"docmind_http_requests_total\{([^}]*)\}\s+(\d+)", line)
            if m:
                labels = m.group(1)
                if 'route="/v1/query"' not in labels:
                    continue
                val = int(m.group(2))
                status = re.search(r'status="(\d{3})"', labels)
                if status:
                    d[status.group(1)] = val
    return d


status_counts = parse_counter(metrics_txt)

# Count 5xx errors
fivexx = sum(v for code, v in status_counts.items() if int(code) >= 500)


# Build final JSON
final_report = {
    "requests": load_report.get("requests", 0),
    "duration_seconds": load_report.get("duration_seconds", 0),
    "rps": load_report.get("rps", 0),
    "p50": load_report.get("p50", 0),
    "p95": load_report.get("p95", 0),
    "p99": load_report.get("p99", 0),
    "status_counts": status_counts,
    "timeouts": load_report.get("timeouts", 0),
    "mem_peak_rss_mb": round(peak_mem_mb, 2),
    "l1_errors_5xx_and_oom": fivexx + (1 if oom else 0),
}

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    json.dump(final_report, f, indent=2)

print(f"Load test report written to {OUTPUT_PATH}")

# Optionally run gates checks
os.system("python evaluation/check_gates.py --results evaluation/results/load-m7.json --stage load")
os.system(
    "python evaluation/check_gates.py"
    " --results evaluation/results/load-m7.json --stage memory"
)
