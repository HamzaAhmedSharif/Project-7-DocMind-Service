# DocMind Service

[
![ci](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml/badge.svg)
](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml)

![license](https://img.shields.io/badge/license-MIT-green)

A RAG service built on top of [DocMind Agent](https://github.com/HamzaAhmedSharif/Project-6-DocMind-Agent), developed in the open with every claim backed by a measurement.

**Status: milestone M6 of 8 (offline implementation complete; provider-dependent measurements and the live key checks are pending).** `POST /v1/query` and the document endpoints work end to end against Postgres/pgvector with ONNX embeddings; API keys, tenants, per-key limits, quotas, guardrails and the semantic cache are built and tested offline. The language model provider is the fake one by default. Every push and pull request runs the gates registered in `evaluation/gates.json`, the image is built, scanned and smoke-tested in CI, and one deliberately bad pull request proves the retrieval gate blocks a regression. Nothing below is claimed as built until its milestone is done.

## Quality gates

Pre-registered in `evaluation/gates.json` before the first measurement; [`docs/EVALUATION.md`](docs/EVALUATION.md) explains what each one measures and how the reference fixtures were built.

| Gate | Check | Blocks merge |
|---|---|---|
| G1 | `ruff check` and `ruff format --check` | yes |
| G2 | unit tests | yes |
| G3 | OpenAPI contract drift (`git diff openapi.json`) | yes |
| G4 | retrieval eval: E2 top-10 overlap ≥ 0.90 and E3 key facts ≥ 23/26 † (E1 diagnostic) | yes |
| G5 | pinned gitleaks over the full history + pip-audit on `requirements.lock` | yes |
| G6 | image builds; Trivy finds no CRITICAL with a fix (HIGH reported) | yes |
| G7 | compose stack healthy + HTTP smoke test on the built image | yes |

† The E3 threshold was changed from 24 to 23 with a recorded post-hoc entry in `DECISIONS.md`; every table that uses it carries the dagger.

## Reproduce locally

Prerequisites: Docker running (Postgres with pgvector) and Python 3.12 with `requirements-dev.txt` installed.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1                       # lint, format, unit, contract
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Integration -Eval    # + DB/model tests + retrieval gates
```

`-Integration` needs Postgres on `127.0.0.1:5433` (`docker compose -f deploy/compose.dev.yml up -d`); `-Eval` downloads the corpus by hash and writes `evaluation/results/retrieval-local.json`.

## Run the container

The image is single-stage, runs as non-root (uid 10001) and has the ONNX embedding model baked in, so retrieval works without a model download at runtime.

```powershell
docker compose -f deploy/compose.ci.yml up --build --wait
python scripts\smoke_http.py --base http://127.0.0.1:8000 --mode ci
docker compose -f deploy/compose.ci.yml down -v
```

## Release verification

Every push to `main` passes the CI gates (lint, tests, API contract, a retrieval-quality gate, secret and vulnerability scans, a container scan). The release image is then run exactly as built, under a 512 MB memory limit, against the project's managed Postgres (Neon free plan, pgvector) and its LLM provider, and nine automatic checks must pass: the image matches the commit, the service is healthy and ready, the sample corpus is present, a question returns a cited answer, a nonsense question is refused, uploads are blocked for anonymous callers, and the rate limit triggers. Latest run: https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41809139449.

Measured on that run (GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt): readiness 1.102 s, first query 1.98 s, warm query 0.556 s, peak memory 230.8 MiB.

This project has no public instance. No payment card is used anywhere in it, and every free container host checked on 2026-11-04 either required a card or restricted the runtime (see DECISIONS.md). See "Run the container" to run it yourself with Docker.

## Security and limits

The service is not hosted publicly. The M5 release image is verified in CI; the M6 key, tenant, guardrail and cache features are built and tested offline, and the live key checks are part of M6.10. This section describes the design and the offline evidence, not a public deployment.

- **Keys and tenants:** `X-API-Key` is optional. A key is `dm_<8 hex>_<32 URL-safe chars>`; only the prefix and a SHA-256 hash are stored, and keys are revocable. Keyed tenants have isolated documents, a per-key minute window, a per-key daily cap and document/page quotas. Anonymous callers are tenant `public`; anonymous uploads are blocked.
- **Limits:** anonymous demo 5 questions/minute per IP and 300/day; keyed tenants 30/minute and 200/day by default; a shared global cap of 800 provider calls/day; uploads 10 MB/200 pages; 20 documents/500 pages per key. Quota failures return 403 `quota_exceeded`. Limiter state is per process, so this is a single-instance design.
- **Guardrails:** prompt v2 treats retrieved text as untrusted, neutralizes fake citations and delimiter runs, and uses a canary. Unknown citations are removed; a non-refused answer with no valid citation becomes `ungrounded` when `REQUIRE_CITATION` is on; Markdown images and URLs not present in the context are removed; long answers are truncated. `GUARDRAILS_ENABLED=false` reproduces the M3 prompt byte-for-byte.
- **Evidence threshold:** paper 0.35 (refuses 0 of 4 absent questions), demo 0.52 (refuses 6 of 6 off-topic questions), both from retrieval-only calibration; the threshold is per corpus and is not guessed.
- **Cache:** keyed by tenant, corpus version and scope hash; τ = 0.86 from the pre-declared calibration/test split; test-half same-intent hit rate 0.3636 and false-hit share 0.0000. Only non-refused, validated answers are stored; 30-day TTL; at most 500 rows per tenant.
- **Demo query log:** anonymous questions are stored redacted for 30 days (emails, phone numbers, ID-like numbers and links removed; names may remain). Keyed tenants are not logged. Do not enter personal data.
- **Red-team:** 15 poisoned passages, arm off vs on, two repeats. Live R1: arm `on` **0 / 15** attacks succeeded, arm `off` **7 / 15**; R1 passes (`0 / 15 <= 2`, not gating). The `off` arm shows the harness can succeed. Result file: `evaluation/results/redteam-m6.json`.
- **No-citation:** 12 answerable paper questions with the citation check off: **1 / 12** answers had no valid citation and **0 / 12** were refused, so the pre-declared rule keeps `REQUIRE_CITATION=true`; that one answer would become a refusal. Result file: `evaluation/results/no-citation-m6.json`.
- **Not covered:** no WAF or bot protection, no per-IP protection beyond the caps, regex redaction misses names and novel formats, revocation can take up to 60 s, and poisoned facts are out of scope.

Full threat table, test evidence and residual risks: [`docs/SECURITY.md`](docs/SECURITY.md).

## Planned

| Milestone | Deliverable |
|---|---|
| M1 | Contract-first skeleton, tooling, CI skeleton (done) |
| M2 | Service core on fakes: query, citations, errors, request ids, JSON logs (done) |
| M3 | Postgres and pgvector, ONNX embeddings, retrieval parity and recall gate (done) |
| M4 | Full CI/CD with quality gates, image build and scan (done) |
| M5 | Release verification against Neon, landing page, measured numbers (done) |
| M6 | API keys, tenants, rate limits, guardrails, semantic cache (offline built; live checks pending) |
| M7 | Metrics, dashboard, load test, capacity model |
| M8 | Service-level evaluation and write-up |

## Develop locally

```bash
python -m venv .venv        # Python 3.12; activate it, then:
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
uvicorn docmind_service.main:app --reload --no-access-log
```

Open http://127.0.0.1:8000/docs for the interactive contract. After changing routes or schemas, run `python scripts/export_openapi.py`; a test fails if `openapi.json` is out of date.

## Try demo mode

```bash
curl -s http://127.0.0.1:8000/v1/query -H 'content-type: application/json' \
  -d '{"question": "What is self-attention?"}'
```

The answer comes from the fake model and the sample chunks. The response carries citations, usage and a request id, which is also returned in the `X-Request-ID` header; application logs are JSON lines and never contain question or answer text. Anonymous demo questions are stored redacted for 30 days in the demo query log (see "Security and limits").

## Layout

```
docmind_service/   application package (config, schemas, problem details, app)
scripts/           export_openapi, fetch_corpus, make_tiny_pdf, smoke_http, check.ps1, make_lock.ps1
evaluation/        questions, scorer, gates, retrieval runner, committed reference fixtures
deploy/            compose files: dev database, CI app+database stack
tests/             offline tests plus integration/model marked tests
docs/              evaluation guide and security model (docs/SECURITY.md)
Dockerfile         single-stage non-root image with the ONNX model baked in
requirements.lock  Linux lock generated inside the base image (scripts/make_lock.ps1)
openapi.json       committed API contract
DECISIONS.md       decisions and engineering notes, each with its evidence
SECURITY.md        how to report a vulnerability
```

## License

MIT, see `LICENSE`.
