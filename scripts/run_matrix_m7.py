#!/usr/bin/env python3
"""M7.3 load matrix, cache run and soak (manager-written runner).

Runs the Master Script section 9 (M7.3) matrix against local containers
with the fake provider: profile `unconstrained` (512 MB) at concurrency
1/5/10/20 and profile `render-like` (512 MB, --cpus 0.1) at 1/5/10, an
answered-only cache run at concurrency 10, and a 10-minute soak at
concurrency 5. The demo corpus is ingested in the local database as
tenant `public` beforehand (scripts/ingest_corpus.py). Application load
settings follow M7.3 (caps raised, fake provider, cache off for the
matrix). No provider calls are made.

Writes evaluation/results/load-m7.json: per-run records plus the gate
aggregates over every run at concurrency <= 10 under the 512 MB limit:
  l1_errors_5xx_and_oom = responses with status >= 500 + OOM kills
  mem_peak_rss_mb       = highest container memory sample, MB
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from loadtest import REFUSED_WORDS, do_request  # noqa: E402

CONTAINER = "docmind-m7mx"
IMAGE = "docmind-service:m7"
BASE = "http://127.0.0.1:8003"
DB_URL = "postgresql://postgres@host.docker.internal:5433/docmind"
OUT = ROOT / "evaluation" / "results" / "load-m7.json"


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def mem_mb() -> float | None:
    r = sh(
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{.MemUsage}}",
        CONTAINER,
    )
    m = re.match(r"([\d.]+)\s*(MiB|GiB)", r.stdout.strip())
    if not m:
        return None
    v = float(m.group(1))
    return v * 1024 if m.group(2) == "GiB" else v


def start_container(profile: str, cache: bool) -> None:
    sh("docker", "rm", "-f", CONTAINER)
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER,
        "--memory",
        "512m",
        "-p",
        "127.0.0.1:8003:8000",
        "-e",
        "DOCMIND_LLM_PROVIDER=fake",
        "-e",
        f"DOCMIND_DATABASE_URL={DB_URL}",
        "-e",
        "DOCMIND_AUTO_MIGRATE=true",
        "-e",
        "DOCMIND_DEMO_IP_PER_MIN=100000",
        "-e",
        "DOCMIND_DEMO_DAILY_CAP=1000000",
        "-e",
        "DOCMIND_GLOBAL_DAILY_LLM_CAP=1000000",
        "-e",
        f"DOCMIND_CACHE_ENABLED={'true' if cache else 'false'}",
    ]
    if profile == "render-like":
        args += ["--cpus", "0.1"]
    args.append(IMAGE)
    r = sh(*args)
    if r.returncode != 0:
        raise RuntimeError(f"docker run failed: {r.stderr.strip()}")
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE + "/healthz", timeout=3) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("container did not become healthy in 90 s")


def stop_container() -> bool:
    r = sh("docker", "inspect", CONTAINER, "--format", "{{.State.OOMKilled}}")
    oom = r.stdout.strip() == "true"
    sh("docker", "rm", "-f", CONTAINER)
    return oom


def scrape_metrics() -> str:
    with urllib.request.urlopen(BASE + "/metrics", timeout=10) as resp:
        return resp.read().decode("utf-8")


def cpu_seconds(text: str) -> float:
    m = re.search(r"^process_cpu_seconds_total\s+([\d.]+)", text, re.M)
    return float(m.group(1)) if m else 0.0


def make_pool(scenario: str, answered: list[str]) -> list[str]:
    import os
    import random

    if scenario == "answered":
        return list(answered)
    refused = [random.choice(REFUSED_WORDS) + " " + os.urandom(3).hex() for _ in range(12)]
    if scenario == "refused":
        return refused
    pool = answered * 4 + refused
    random.shuffle(pool)
    return pool


def run_load(concurrency: int, duration: int, pool: list[str], sample_every: float = 2.0) -> dict:
    samples: list[float] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            v = mem_mb()
            if v is not None:
                samples.append(v)
            stop.wait(sample_every)

    cpu0 = cpu_seconds(scrape_metrics())
    total = 0
    lat: list[float] = []
    counts: dict[str, int] = {}
    timeouts = 0
    t = threading.Thread(target=sampler, daemon=True)
    t.start()
    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        pending = set()
        idx = 0
        while pending or (time.time() - start) < duration:
            while len(pending) < concurrency and (time.time() - start) < duration:
                pending.add(ex.submit(do_request, BASE, pool[idx % len(pool)]))
                idx += 1
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                status, lat_v, _ = fut.result()
                if status is None:
                    timeouts += 1
                else:
                    counts[str(status)] = counts.get(str(status), 0) + 1
                lat.append(lat_v)
                total += 1
    elapsed = time.time() - start
    stop.set()
    t.join(timeout=5)
    cpu1 = cpu_seconds(scrape_metrics())
    return {
        "requests": total,
        "duration_seconds": round(elapsed, 3),
        "rps": round(total / elapsed, 3) if elapsed else 0,
        "p50": round(statistics.median(lat), 4) if lat else 0,
        "p95": (
            round(statistics.quantiles(lat, n=20)[-1], 4)
            if len(lat) >= 20
            else (round(max(lat), 4) if lat else 0)
        ),
        "p99": (
            round(statistics.quantiles(lat, n=100)[-1], 4)
            if len(lat) >= 100
            else (round(max(lat), 4) if lat else 0)
        ),
        "status_counts": counts,
        "timeouts": timeouts,
        "mem_peak_mb": round(max(samples), 2) if samples else None,
        "mem_end_mb": round(samples[-1], 2) if samples else None,
        "mem_samples": [round(s, 2) for s in samples],
        "cpu_seconds_delta": round(cpu1 - cpu0, 3),
    }


def main() -> int:
    dq = json.loads((ROOT / "evaluation" / "demo_questions.json").read_text(encoding="utf-8"))
    answered = [q["question"] for q in dq["questions"]]
    runs: list[dict] = []

    def one(
        profile: str,
        conc: int,
        scenario: str,
        cache: bool,
        duration: int = 60,
        sample_every: float = 2.0,
        reuse: bool = False,
    ) -> dict:
        if not reuse:
            start_container(profile, cache)
        print(f"RUN profile={profile} c={conc} scenario={scenario} cache={cache}", flush=True)
        rec = run_load(conc, duration, make_pool(scenario, answered), sample_every)
        rec.update(
            profile=profile,
            concurrency=conc,
            scenario=scenario,
            cache_enabled=cache,
            duration_requested_s=duration,
        )
        if not reuse:
            rec["oom_killed"] = stop_container()
        runs.append(rec)
        print(
            f"  -> {rec['requests']} req, rps={rec['rps']}, p95={rec['p95']}, "
            f"5xx={sum(v for k, v in rec['status_counts'].items() if int(k) >= 500)}, "
            f"peak={rec['mem_peak_mb']} MB, oom={rec.get('oom_killed')}",
            flush=True,
        )
        return rec

    # unconstrained matrix (one container, cache off)
    start_container("unconstrained", False)
    for conc in (1, 5, 10, 20):
        one("unconstrained", conc, "mixed", False, reuse=True)
        time.sleep(10)
    oom_block = stop_container()
    for r in runs[-4:]:
        r["oom_killed"] = oom_block

    # render-like matrix (one container, cache off)
    start_container("render-like", False)
    for conc in (1, 5, 10):
        one("render-like", conc, "mixed", False, reuse=True)
        time.sleep(10)
    oom_block = stop_container()
    for r in runs[-3:]:
        r["oom_killed"] = oom_block

    # cache run: answered only, cache on, unconstrained, c10
    one("unconstrained", 10, "answered", True)

    # soak: mixed c5, 10 minutes, samples every 10 s
    start_container("unconstrained", False)
    print("RUN soak c=5 mixed 600s", flush=True)
    soak = run_load(5, 600, make_pool("mixed", answered), sample_every=10.0)
    soak.update(
        profile="unconstrained",
        concurrency=5,
        scenario="mixed-soak",
        cache_enabled=False,
        duration_requested_s=600,
    )
    soak["oom_killed"] = stop_container()
    soak_samples = soak.pop("mem_samples")
    soak["mem_first_minute_end_mb"] = (
        soak_samples[6] if len(soak_samples) > 6 else (soak_samples[-1] if soak_samples else None)
    )
    soak["mem_samples_10s"] = soak_samples
    runs.append(soak)
    print(f"  -> soak {soak['requests']} req, peak={soak['mem_peak_mb']} MB", flush=True)

    gate_runs = [r for r in runs if r["concurrency"] <= 10]
    l1 = sum(
        sum(v for k, v in r["status_counts"].items() if int(k) >= 500)
        + (1 if r.get("oom_killed") else 0)
        for r in gate_runs
    )
    mem_peak = max(r["mem_peak_mb"] for r in gate_runs if r["mem_peak_mb"] is not None)
    headline = next(
        r
        for r in runs
        if r["profile"] == "unconstrained" and r["concurrency"] == 10 and r["scenario"] == "mixed"
    )
    doc = {
        "requests": headline["requests"],
        "duration_seconds": headline["duration_seconds"],
        "rps": headline["rps"],
        "p50": headline["p50"],
        "p95": headline["p95"],
        "p99": headline["p99"],
        "status_counts": headline["status_counts"],
        "timeouts": headline["timeouts"],
        "mem_peak_rss_mb": mem_peak,
        "l1_errors_5xx_and_oom": l1,
        "conditions": {
            "image": IMAGE,
            "database": "local docmind-pg (pgvector pg17), demo corpus ingested as tenant public",
            "provider": "fake",
            "app_settings": "caps raised per M7.3; cache off except the cache run",
            "profiles": "unconstrained = --memory 512m; render-like = --memory 512m --cpus 0.1",
            "gate_scope": "all runs at concurrency <= 10 under 512 MB, soak included",
            "headline_run": "unconstrained, mixed, concurrency 10, cache off",
        },
        "runs": runs,
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"WROTE {OUT} l1={l1} mem_peak={mem_peak}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
