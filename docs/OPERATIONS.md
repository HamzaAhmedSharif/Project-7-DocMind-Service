# Operations (M5 / M7 skeleton)

## Hosting options evaluated (all read on 2026-11-04)

| Host | What the sources say | Verdict |
|---|---|---|
| Render | Demanded a card at signup (Sol, 2026-11-04); an independent test also reports a card (with a small hold) is needed to deploy a web service | **OUT** (trigger fired) |
| Koyeb | Pricing FAQ: a card is required "to prevent fraud and abuse", verified by a $29 pre-authorization hold; acquired by Mistral AI in February 2026; new accounts start on a paid plan | **OUT** |
| Hugging Face Docker Space | Hub docs: "Gradio and Docker Spaces run on compute and require a paid plan to create"; only static Spaces are free (forum thread of July 2026: Docker SDK marked Paid) | **OUT, confirmed** |
| Hugging Face Gradio Space on free ZeroGPU (2 per free account; Project 6 uses one) | Technically able to start an ASGI app, so "presumed out" is not strictly true. Refuted for this project for three reasons: it is not the container we gate (a Gradio wrapper and a requirements install replace the audited image), ZeroGPU demands a GPU-decorated function so a CPU API would need a no-op one (a workaround third parties document, against the purpose of the allotment and a policy risk), and it would take the second and last free slot | **OUT (refuted: possible, but distorts the artifact and the platform's terms)** |
| Northflank Sandbox | Pricing page: "Free, No card needed, always on, 2 services, up to $20/mo of resources". Billing docs: "all users must add a payment method to start creating resources on Northflank, regardless of plan selection". Railway's comparison page and two directories also say a card is required. The primary sources disagree; the docs are explicit and recent | **PROBE (bounded, A1.6); presumed out until it passes** |
| SnapDeploy | Only vendor pages: no card, 512 MB and 0.25 vCPU per container, 100 hours per month, auto-sleep with a wake of about a minute. The same vendor's blogs listed Render as card-free, which today's signup disproved, so its claims are unverified | **PROBE (bounded, A1.6); lowest confidence** |
| Fly.io, Railway, Google Cloud Run, Oracle | Card or billing account (Sol 2026-11-04; earlier research of 2026-10-27) | **OUT** |

Evidence log: `northflank.com/docs/v1/application/billing/project-types`, `northflank.com/pricing`, `docs.railway.com/platform/compare-to-northflank`, `koyeb.com/docs/faqs/pricing`, `huggingface.co/docs/hub/en/spaces-overview`, the Hugging Face forum thread "Docker SDK now marked as Paid" (July 2026), `snapdeploy.dev` (vendor pages).

## How to run the release image

The release image is `ghcr.io/hamzaahmedsharif/docmind-service:sha-<7-char-commit>`. It carries its commit in `DOCMIND_GIT_SHA`, set at build time with `--build-arg GIT_SHA=<commit>`, and the revision in the `org.opencontainers.image.revision` label.

1. Pull the image and read its revision label:
   `docker pull ghcr.io/hamzaahmedsharif/docmind-service:sha-<sha7>`
   `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' <image>`
2. Run it with the non-secret release configuration and the three secrets forwarded from the environment (never on the command line):
   `docker run -d --name release-smoke --memory 512m -p 127.0.0.1:8000:8000 --env-file deploy/release.env -e DOCMIND_DATABASE_URL -e DOCMIND_DATABASE_URL_DIRECT -e DOCMIND_LLM_API_KEY <image>`
3. Run the release smoke:
   `python scripts/smoke_http.py --base http://127.0.0.1:8000 --mode ephemeral --expect-commit <sha> --expect-image-revision <sha> --check-limits --json-out smoke.json`
4. Local fallback when the production secrets are not stored in GitHub:
   `scripts/run_release_local.ps1` (reads `deploy/release.env`, `.env.neon` and `.env`; never prints them).

## Variable list (secret vs not)

| Variable | Secret? | Description |
|---|---|---|
| `DOCMIND_LLM_API_KEY` | yes | Groq key for hosted provider |
| `DOCMIND_DATABASE_URL` | yes | Pooled connection string |
| `DOCMIND_DATABASE_URL_DIRECT` | yes | Direct connection string |
| `DOCMIND_LLM_PROVIDER` | no | `fake` or `hosted` |
| `DOCMIND_ENVIRONMENT` | no | `dev`, `test`, `prod` |
| `DOCMIND_UPLOADS_ENABLED` | no | `true` / `false` |
| `DOCMIND_TRUST_PROXY_HOPS` | no | `0` or `1` |
| `DOCMIND_AUTO_MIGRATE` | no | `true` / `false` |
| `DOCMIND_DEMO_DAILY_CAP` | no | Daily question cap (UTC day) |
| `DOCMIND_DEMO_IP_PER_MIN` | no | Per-IP questions per minute |
| `DOCMIND_GIT_SHA` | no | Commit baked into the image |
| `DOCMIND_GLOBAL_DAILY_LLM_CAP` | no | Global request cap (M6) |
| `DOCMIND_EVIDENCE_MIN_SCORE` | no | Evidence gate threshold (M6) |
| `DOCMIND_CACHE_ENABLED` | no | Cache default (M6) |
| `DOCMIND_CACHE_THRESHOLD` | no | Cache similarity threshold (M6) |

## Rotate each secret

1. Generate a new value in the provider console (e.g., Groq key, Neon password).
2. Add the new value to the secret store used by the deployment (GitHub environment secret or the local `.env.neon`/`.env`).
3. Redeploy or restart the service.
4. Run the release smoke (or the local fallback) and confirm it passes.
5. Remove the old secret.

## M5 specific

- Neon scales to zero after 5 minutes idle; the pooled connection string reconnects.
- `UPLOADS_ENABLED=false` disables `POST/DELETE /v1/documents` (returns 403).
- Per-IP limiter: `DEMO_IP_PER_MIN=5` (sliding 60-second window).
- Daily cap: `DEMO_DAILY_CAP=300` (UTC day, resets at midnight).
- The release smoke runs on every green `main` CI run and costs at most one provider request.

## Release-smoke and neon-seed workflows

### release-smoke (`.github/workflows/release-smoke.yml`)

- Runs automatically after a successful `ci.yml` run on `main`, and by manual dispatch (`workflow_dispatch`). It never triggers on `pull_request`.
- Pulls `ghcr.io/hamzaahmedsharif/docmind-service:sha-<7-char-commit>` and runs the nine-check ephemeral smoke under a 512 MB limit against Neon and the real provider.
- Secrets come from the GitHub environment `release-smoke` (restricted to `main`), by name: `DOCMIND_DATABASE_URL`, `DOCMIND_DATABASE_URL_DIRECT`, `DOCMIND_LLM_API_KEY`. The workflow forwards them with bare `-e NAME`; it never prints them and never runs `set -x`.
- Costs at most one provider request per run. `python scripts/provider_budget.py --used-today <local-calls>` counts today's release-smoke runs from the workflow-run list (upper bound: one request per run).
- Failure output: the last 40 container log lines with DSNs redacted; the `smoke.json` artifact is uploaded when available.

### neon-seed (`.github/workflows/neon-seed.yml`)

- Manual only (`workflow_dispatch`); it never runs automatically and never triggers on `pull_request`.
- Re-run only when the demo corpus changes: it applies migrations (`AUTO_MIGRATE=true`), ingests `evaluation/demo_corpus.json` into Neon, and runs `scripts/check_demo_corpus.py`.
- Uses the same `release-smoke` environment secrets; same bare `-e NAME` forwarding.
- The last seed (2026-11-04) created 3 documents / 639 chunks; database 7896 kB -> 11 MB; demo-check top-3 results identical to the local reference file.


## M7 — Running, monitoring and repairing the service

### Overview and endpoints

DocMind Service is a single FastAPI application (one container, one
process). Public surface:

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /` | none | Landing page |
| `GET /healthz` | none | Liveness; never touches the database |
| `GET /readyz` | none | Readiness; checks the database pool |
| `POST /v1/query` | anonymous (demo limits) or API key | Answers with citations or a refusal |
| `GET /v1/documents` | anonymous lists the `public` tenant; keyed lists own tenant | |
| `POST /v1/documents` | API key with `write` scope, uploads enabled | Anonymous writes are 403 |
| `DELETE /v1/documents/{id}` | API key with `write` scope | Own tenant only |
| `GET /metrics` | see the access rule below | Prometheus exposition; never touches the database |

### How to run locally

Observability stack (app + Postgres + Prometheus + Grafana, all ports
bound to 127.0.0.1):

```
docker compose -f deploy/observability/compose.yml up --build
```

Grafana is at `http://127.0.0.1:3000` with the distribution's default
admin credentials. That is acceptable **only** because every published
port is bound to 127.0.0.1; never rebind Grafana or Prometheus to a
shared interface without changing the credentials first. Prometheus
scrapes `app:8000/metrics` every 5 seconds; the dashboard `DocMind
Service` (uid `docmind`) is provisioned from
`deploy/observability/dashboards/docmind.json`.

Plain Docker (release image): see "How to run the release image" above.

### Settings (every `Settings` field)

Environment variables carry the `DOCMIND_` prefix. Secret values are
never printed, logged or committed.

| Setting | Default | Secret | Meaning |
|---|---|---|---|
| `environment` | `dev` | no | `dev`, `test` or `prod`; prod tightens the `/metrics` rule |
| `log_level` | `INFO` | no | JSON log level |
| `default_top_k` | 10 | no | Retrieval depth per query |
| `max_upload_mb` | 10 | no | Upload size limit (oversize → 413) |
| `max_pages` | 200 | no | Per-document page limit |
| `default_mode` | `single` | no | Query orchestration mode |
| `database_url` | — | yes | Pooled Postgres connection string |
| `database_url_direct` | — | yes | Direct Postgres connection string (migrations) |
| `auto_migrate` | false | no | Apply SQL migrations at startup |
| `llm_provider` | `fake` | no | `fake` (offline) or `hosted` |
| `llm_base_url` | `https://api.groq.com/openai/v1` | no | OpenAI-compatible endpoint |
| `llm_model` | `openai/gpt-oss-120b` | no | Hosted model id |
| `llm_api_key` | — | yes | Hosted provider key |
| `llm_reasoning_effort` | `low` | no | Reasoning effort hint |
| `llm_max_completion_tokens` | 1024 | no | Completion token ceiling |
| `llm_max_wait_seconds` | 20 | no | Max provider queue wait before shedding |
| `hosted_rpm` | 20 | no | Provider requests/minute pacing (90% buckets) |
| `hosted_tpm` | 8000 | no | Provider tokens/minute pacing (90% buckets) |
| `embedding_model` | `sentence-transformers/all-MiniLM-L6-v2` | no | ONNX embedding model |
| `model_cache_dir` | — | no | fastembed model cache location |
| `git_sha` | — | no | Commit baked into the image at build time |
| `uploads_enabled` | true | no | Master switch for upload/delete (release: false) |
| `demo_daily_cap` | 300 | no | Anonymous questions per UTC day |
| `demo_ip_per_min` | 5 | no | Anonymous questions per minute per IP |
| `trust_proxy_hops` | 0 | no | Proxies in front of the app (client-IP derivation) |
| `auth_cache_seconds` | 60 | no | API-key lookup cache |
| `key_rpm` | 30 | no | Per-key requests per minute |
| `key_daily_queries` | 200 | no | Per-key questions per UTC day |
| `key_max_documents` | 20 | no | Per-key document quota (403 `quota_exceeded`) |
| `key_max_pages` | 500 | no | Per-key page quota (403 `quota_exceeded`) |
| `global_daily_llm_cap` | 800 | no | All-tenant provider calls per UTC day |
| `metrics_token` | — | yes | Bearer token for `/metrics` when set |
| `guardrails_enabled` | true | no | Prompt-injection guardrails (prompt v2) |
| `require_citation` | true | no | Refuse answers without a valid citation |
| `canary` | — | yes | Guardrail canary string (never logged) |
| `max_answer_chars` | 4000 | no | Answer truncation limit |
| `evidence_min_score` | 0.2 | no | Evidence gate (release demo value: 0.52, calibrated) |
| `cache_enabled` | true | no | Semantic cache master switch |
| `cache_threshold` | 0.86 | no | Cache similarity threshold (calibrated, C1) |
| `cache_ttl_days` | 30 | no | Semantic cache entry lifetime |
| `query_log_days` | 30 | no | Redacted demo query-log retention |

### The `/metrics` access rule

- `environment=prod` and no `metrics_token` set → **404** (feature off).
- `metrics_token` set (any environment) → `Authorization: Bearer
  <token>` required (constant-time compare); anything else → **401**.
- dev/test with no token → open (local dashboards and tests).

A scrape never touches the database: pool gauges are read from the
in-process pool statistics, so scraping cannot wake a scaled-to-zero
Neon instance.

### Free-tier behavior

- Neon scales to zero after 5 minutes idle; the pooled connection
  string reconnects on the next database-touching request. `/healthz`
  does not touch the database, so health checks never wake it.
- The per-IP rate-limit window is per-process in-memory state; a
  restart resets it. The **daily cap is Postgres-backed**
  (`usage_daily`, one row per UTC day and scope) and is therefore
  shared across processes and restarts — every instance pointed at the
  same database spends from the same counter. The cap is incremented
  *before* the provider call, so a failed provider call still spends
  budget (by design: it prevents retry storms against a dead
  provider).
- There is no persistent public host (Amendment A1): the release image
  is verified by the `release-smoke` workflow under a 512 MB limit
  against Neon after every green `main` CI run. No scheduled pings are
  used anywhere.

### Budget accounting

Provider requests are counted per UTC day across everything that uses
the key: the release-smoke (at most 1 per run), local measurement runs
and any live check. The combined ceiling is 800/day
(`global_daily_llm_cap`); M8's service evaluation has its own budget
of at most 100 requests (at most 60 per UTC day). Check the ledger
before and after any provider run:

```
python scripts/provider_budget.py --used-today <successful local calls>
```

### Monitoring — what the dashboard panels mean

- **Request rate by route** — `docmind_http_requests_total` rate; a
  spike on `/v1/query` with flat outcomes means refusals or errors.
- **p50/p95 latency of `/v1/query`** — retrieval + provider time;
  the p95 panel separates the retrieval path from provider wait.
- **Responses by status class** — 429 growth = caps; 5xx growth = the
  incident table below.
- **Query outcomes (stacked)** — answered vs `cache_hit` vs each
  refusal kind; a rising `refused_low_evidence` share after an ingest
  change means the corpus or threshold moved.
- **Cache hit ratio** — hits / (hits + misses); a collapse after a
  deploy points at a corpus-version or threshold change.
- **Provider tokens per minute** — against the 8,000/min limit with a
  constant line at 7,200 (the 90% pacing rule).
- **Provider wait time p95** — queueing inside the pacing buckets;
  sustained growth precedes load shedding (`docmind_llm_shed_total`).
- **Guardrail events** — canary hits, invalid citations removed, URLs
  and images stripped, truncations, ungrounded blocks.
- **Database pool state** — size / available / waiting; waiting > 0
  under load means the pool is the bottleneck.
- **Resident memory** — against the 512 MB line; the M7 load record
  (below) peaked at 225.8 MB under the gate profile.
- **Provider calls in the last 24 h** — `increase()` of the calls
  counter; reconcile with the budget ledger.

### Incident table

| Symptom | Likely cause | Check | Action |
|---|---|---|---|
| 503 with `Retry-After` on queries | Database down, or provider down/shed | `/readyz`; `docmind_db_errors_total`; provider wait panel | Restore the database (service recovers without a restart — drill 1); for the provider, wait or rotate the key |
| 429 `daily_cap_reached` | Global or per-IP daily cap reached | Query-outcome panel (`cap_reached`, `rate_limited`) | Expected behavior; caps reset at UTC midnight; do not raise caps on the release config |
| Slow first request | Cold process: model load + first embed | Startup logs; compare with the cold-start drill | Expected once per process start; warm requests are the measured path |
| `/readyz` 503 | Database unreachable | `docker ps` / Neon console; pool gauges | Restart the database; the app recovers on its own (drill 1) |
| Memory restarts (OOM) | Container over its 512 MB limit | `docker inspect` OOMKilled; memory panel vs the M7 peak | Check for an upload or corpus change; the M4.8 memory ladder applies |
| Stuck deploy | CI or release-smoke red | GitHub Actions logs for `ci` then `release-smoke` | Fix forward on `main`; the smoke re-runs on the next green CI |
| G8 failing | Release image behavior changed | `release-smoke` run log (DSNs redacted) | Reproduce locally with the release image and `deploy/release.env` |
| Suspected leaked secret | Key or DSN in a log, screenshot or commit | `gitleaks` over history | Rotate first (below), then purge; never rewrite history silently |

### Rotate each secret

Groq key, Neon password and `METRICS_TOKEN` follow the five steps in
"Rotate each secret" above. API keys for tenants are rotated with the
admin CLI: `python -m docmind_service.admin create-key --tenant <t>
--label <l> --write` issues a new key (shown once); revoke the old one
with the admin CLI afterwards.

### Failure drills (verified locally on 2026-11-05)

Drills ran against the release image under `-m 512m`; drills 2, 3 and
5 used an isolated drill database, because the daily counter is
Postgres-backed and shared (see Free-tier behavior).

| # | Drill | Observed |
|---|---|---|
| 1 | Database stopped | `/healthz` 200, `/readyz` 503, `/v1/query` **503 with `Retry-After: 30`**, outcome `retrieval_error`; service recovered 2.3 s after the database restarted, no app restart. The drill's first run exposed a 500 here (the cache path did not translate database errors); fixed in this milestone with regression tests (`tests/test_db_down.py`). |
| 2 | Provider unreachable (hosted, dead base URL) | `/v1/query` **503**, outcome `provider_error`. |
| 3 | Daily cap = 1, release evidence threshold | First query 200 answered; second provider-needing query **429 `daily_cap_reached` with `Retry-After`** (seconds to UTC midnight); a low-evidence question still refused 200 without a provider call. |
| 4 | Cold start | `/healthz` 1.69 s, `/readyz` 1.77 s. |
| 5 | Uploads: 11 MB / not-a-PDF / fake-encrypted / empty (keyed) | **413 / 422 / 422 / 422**; memory after 204.7 MiB. |

### Load record (M7.3)

102,937 requests across the matrix (unconstrained and render-like
profiles, mixed and answered workloads, plus a 600 s soak): every run
HTTP 200, zero timeouts, zero OOM kills. Headline unconstrained c10
mixed: 113.6 rps at p95 0.107 s. Soak memory stayed flat: 208.4 MB at
one minute → 208.1 MB at the end.

Full per-run data: `evaluation/results/load-m7.json`. Gates: L1
(5xx + OOM at concurrency ≤ 10 under 512 MB) = 0; MEM (peak RSS)
= 225.8 MB against the 480 MB threshold.

### Known limits

- Single instance only: the per-IP limiter is in-process and resets on
  restart; Prometheus counters are per process. (The daily cap is
  Postgres-backed — see Free-tier behavior.)
- Query-log redaction is regex-based; novel PII formats can slip
  through (see `docs/SECURITY.md`).
- No availability promise is made: the only service levels stated are
  measured numbers with their conditions (this file and
  `docs/FACTS.md`).
