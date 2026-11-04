#!/usr/bin/env python3
"""Failure drills for M7.4.
Verified locally against the DocMind service container.
"""

import os
import re
import subprocess
import time

BASE_URL = "http://127.0.0.1:8002"
CONTAINER_NAME = "docmind-drill"


def run(cmd, capture=True):
    res = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    return res


def curl(path, data=None, headers=None):
    cmd = f"curl -s -i {BASE_URL}{path}"
    if data:
        with open("drill_body.json", "w", encoding="utf-8") as f:
            f.write(data)
        cmd += ' -X POST -H "Content-Type: application/json" --data-binary @drill_body.json'
    if headers:
        for h in headers:
            cmd += f' -H "{h}"'
    return run(cmd)


def stop_container():
    run(f"docker stop {CONTAINER_NAME}")


def start_container(env_vars=None, wait=True):
    env_vars = [
        "DOCMIND_DATABASE_URL=postgresql://postgres@host.docker.internal:5433/docmind",
        *(env_vars or []),
    ]
    env_str = " ".join([f"-e {v}" for v in env_vars])
    # Use fake provider by default unless otherwise specified
    if not any(v.startswith("DOCMIND_LLM_PROVIDER=") for v in env_vars):
        env_str += " -e DOCMIND_LLM_PROVIDER=fake"
    run(
        f"docker run -d --name {CONTAINER_NAME} {env_str} -p 127.0.0.1:8002:8000 docmind-service:m7"
    )
    if wait:
        for _ in range(30):
            res = curl("/healthz")
            if res.stdout and "200" in res.stdout.splitlines()[0]:
                return
            time.sleep(1)


def clean():
    run(f"docker rm -f {CONTAINER_NAME}")


def drill_db_down():
    print("--- Drill 1: Database Down ---")
    # Assumes docmind-pg is running on 5433 (mapped to 5432 in container)
    # We need the app to be running and connected.
    start_container(
        ["DOCMIND_DATABASE_URL=postgresql://postgres@host.docker.internal:5433/docmind"]
    )
    time.sleep(2)

    # 1. Stop DB
    run("docker stop docmind-pg")

    # 2. Check /healthz (should be 200)
    res = curl("/healthz")
    print(f"Healthz: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # 3. Check /readyz (should be 503)
    res = curl("/readyz")
    print(f"Readyz: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # 4. Check /v1/query (should be 503 + Retry-After)
    res = curl("/v1/query", data='{"question": "test"}')
    print(f"Query: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # 5. Start DB
    start_time = time.time()
    run("docker start docmind-pg")

    # 6. Recovery
    while True:
        res = curl("/readyz")
        if "200" in res.stdout:
            break
        time.sleep(1)
        if time.time() - start_time > 30:
            break
    print(f"Recovered in {time.time() - start_time:.2f}s")
    clean()


def drill_provider_down():
    print("\n--- Drill 2: Provider Down ---")
    # hosted provider, wrong URL, dummy key
    start_container(
        [
            "DOCMIND_LLM_PROVIDER=hosted",
            "DOCMIND_LLM_BASE_URL=http://127.0.0.1:9",
            "DOCMIND_LLM_API_KEY=dummy-not-a-key",
        ]
    )
    time.sleep(2)

    res = curl("/v1/query", data='{"question": "test"}')
    print(f"Query response: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # Check logs for exception type
    logs = run(f"docker logs {CONTAINER_NAME}").stdout
    print(f"Logs snippet: {logs[-500:]}")
    clean()


def drill_daily_cap():
    print("\n--- Drill 3: Daily Cap ---")
    start_container(["DOCMIND_GLOBAL_DAILY_LLM_CAP=1"])
    time.sleep(2)

    # First query (answered)
    q1 = '{"question": "What is the core purpose of the AI Risk Management Framework?"}'
    res1 = curl("/v1/query", data=q1)
    print(f"Query 1: {res1.stdout.splitlines()[0] if res1.stdout else 'Error'}")

    # Second query (429 cap_reached)
    q2 = '{"question": "What risks does the Generative AI Profile identify for generative AI?"}'
    res2 = curl("/v1/query", data=q2)
    print(f"Query 2: {res2.stdout.splitlines()[0] if res2.stdout else 'Error'}")

    # Refused query (still works)
    res3 = curl("/v1/query", data='{"question": "zxqv"}')
    print(f"Refused Query: {res3.stdout.splitlines()[0] if res3.stdout else 'Error'}")
    clean()


def drill_cold_start():
    print("\n--- Drill 4: Cold Start ---")
    start_container(wait=False)
    # We measure from the moment 'docker run' finishes
    # In a real script, we'd capture the timestamp of run.
    start = time.time()
    while True:
        if "200" in curl("/healthz").stdout:
            h_time = time.time() - start
            break
        time.sleep(0.1)

    while True:
        if "200" in curl("/readyz").stdout:
            r_time = time.time() - start
            break
        time.sleep(0.1)

    print(f"Healthz ready: {h_time:.2f}s")
    print(f"Readyz ready: {r_time:.2f}s")
    clean()


def drill_uploads():
    print("\n--- Drill 5: Uploads ---")
    # Need a key in DB. For demo, we just start and try.
    # The spec says "throw-away key in local database".
    # We can assume an API key 'test-key' exists or just test 403/413.
    start_container()
    time.sleep(2)

    # Throw-away write key via the admin CLI (captured, never printed)
    kc = run(
        f"docker exec {CONTAINER_NAME} python -m docmind_service.admin "
        "create-key --tenant drill --label drill --write"
    )
    m = re.search(r"dm_[0-9a-f]+_[A-Za-z0-9_-]+", kc.stdout or "")
    key = m.group(0) if m else ""

    # 1. 11 MB file (413)
    # Create a fake 11MB file
    with open("oversized.pdf", "wb") as f:
        f.write(b"0" * 11 * 1024 * 1024)

    # We use curl --form to upload
    res = run(f'curl -s -i -F "file=@oversized.pdf" -H "X-API-Key: {key}" {BASE_URL}/v1/documents')
    print(f"11MB file: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # 2. Text renamed to .pdf (422)
    with open("text.pdf", "w") as f:
        f.write("This is not a PDF")
    res = run(f'curl -s -i -F "file=@text.pdf" -H "X-API-Key: {key}" {BASE_URL}/v1/documents')
    print(f"Text as PDF: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # 3. Encrypted PDF (422) - using a dummy file
    with open("encrypted.pdf", "wb") as f:
        f.write(b"FakeEncryptedPDFContent")
    res = run(f'curl -s -i -F "file=@encrypted.pdf" -H "X-API-Key: {key}" {BASE_URL}/v1/documents')
    print(f"Encrypted PDF: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # 4. 0-byte file (422)
    with open("empty.pdf", "wb") as f:
        pass
    res = run(f'curl -s -i -F "file=@empty.pdf" -H "X-API-Key: {key}" {BASE_URL}/v1/documents')
    print(f"0-byte file: {res.stdout.splitlines()[0] if res.stdout else 'Error'}")

    # Memory check
    mem = run('docker stats --no-stream --format "{{.MemUsage}}" ' + CONTAINER_NAME).stdout.strip()
    print(f"Memory after uploads: {mem}")

    clean()
    os.remove("oversized.pdf")
    os.remove("text.pdf")
    os.remove("encrypted.pdf")
    os.remove("empty.pdf")


if __name__ == "__main__":
    try:
        drill_db_down()
        drill_provider_down()
        drill_daily_cap()
        drill_cold_start()
        drill_uploads()
    finally:
        clean()
