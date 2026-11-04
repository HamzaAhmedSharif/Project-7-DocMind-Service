#!/usr/bin/env bash
# Release smoke (A1.5). Never uses `set -x`, never prints the environment or a secret.
set -euo pipefail

: "${SHA:?SHA is required}"
IMAGE="ghcr.io/hamzaahmedsharif/docmind-service:sha-${SHA:0:7}"
CONTAINER=release-smoke
MEM_FILE=mem.txt
SMOKE_FILE=smoke.json
IP_PER_MIN=$(grep -E '^DOCMIND_DEMO_IP_PER_MIN=' deploy/release.env | cut -d= -f2 || true)
IP_PER_MIN=${IP_PER_MIN:-5}

cleanup() {
  status=$?
  if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    docker logs --tail 40 "$CONTAINER" 2>&1 \
      | sed -E 's#postgres(ql)?://[^[:space:]]+#[redacted]#g' || true
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

docker pull "$IMAGE"
REV=$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE")
if [ -z "$REV" ] || [ "$REV" = "<no value>" ]; then
  echo "image has no org.opencontainers.image.revision label" >&2
  exit 1
fi

docker run -d --name "$CONTAINER" --memory 512m -p 127.0.0.1:8000:8000 \
  --env-file deploy/release.env \
  -e DOCMIND_DATABASE_URL -e DOCMIND_DATABASE_URL_DIRECT -e DOCMIND_LLM_API_KEY \
  "$IMAGE" >/dev/null

(
  while docker inspect "$CONTAINER" >/dev/null 2>&1; do
    docker stats --no-stream --format '{{.MemUsage}}' "$CONTAINER" >> "$MEM_FILE" 2>/dev/null || true
    sleep 2
  done
) &
SAMPLER=$!

set +e
python3 scripts/smoke_http.py --base http://127.0.0.1:8000 --mode ephemeral \
  --expect-commit "$SHA" --expect-image-revision "$REV" --check-limits \
  --ip-per-min "$IP_PER_MIN" --json-out "$SMOKE_FILE" --mem-file "$MEM_FILE" \
  --runner-type github-hosted --container-limit 512m \
  --conditions "GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt"
SMOKE_EXIT=$?
set -e

kill "$SAMPLER" >/dev/null 2>&1 || true

if [ -n "${GITHUB_STEP_SUMMARY:-}" ] && [ -f "$SMOKE_FILE" ]; then
  python3 - "$SMOKE_FILE" >> "$GITHUB_STEP_SUMMARY" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print("| Check | Result |")
print("|---|---|")
for check in data["checks"]:
    print(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} |")
print("")
print("| Number | Value |")
print("|---|---|")
info = data.get("info", {})
for key in ("readyz_first_latency_s", "first_query_latency_s", "warm_query_latency_s", "mem_peak_mib"):
    if key in info:
        print(f"| {key} | {info[key]} |")
print(f"| conditions | {info.get('conditions', '')} |")
PY
fi

exit "$SMOKE_EXIT"
