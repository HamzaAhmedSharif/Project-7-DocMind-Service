# DocMind Service

[![ci](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml/badge.svg)](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml)

![license](https://img.shields.io/badge/license-MIT-green)

A production-style RAG service on free tiers: upload PDFs, ask questions, get
answers with page-level citations, behind API keys, rate limits, guardrails
and a semantic cache. It is the service form of
[DocMind Agent](https://github.com/HamzaAhmedSharif/Project-6-DocMind-Agent)
(Project 6), built to find out what changes when a notebook-grade RAG pipeline
has to survive an API contract, tenants, abuse controls and a load test.

**What it is not:** a public product, and no payment card exists anywhere
in the project. A public UI demo runs on a free Hugging Face Space (see
Live demo); the raw API is not publicly exposed, and the release image is
verified in CI against managed Postgres and the real provider (below). The evaluation corpus
is one famous paper, so the model's own memory of it is a confound; held-out
evaluation on papers the model cannot know is Project 9's work, prepared here
as `evaluation/heldout/manifest.json`.

## Release verification

Every push to `main` passes the CI gates (lint and format, unit tests, the
OpenAPI contract check, a retrieval-quality gate, secret and vulnerability
scans, a container scan and a smoke test). The pushed image is then run
exactly as built, under a 512 MB memory limit, against the project's managed
Postgres (Neon free plan, pgvector) and its LLM provider, and nine checks
must pass: the image matches the commit, the service is healthy and ready,
the sample corpus is present, a question returns a cited answer, a nonsense
question is refused, uploads are blocked for anonymous callers, and the rate
limit triggers. Latest run:
https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/42343057863

Measured on the M5 verification run (GitHub-hosted runner, 512 MB container
limit, Neon free plan, Frankfurt): readiness 1.102 s, first query 1.98 s,
warm query 0.556 s, peak memory 230.8 MiB. Conditions for every number are in
[`docs/FACTS.md`](docs/FACTS.md).

## Live demo

A public demo of the service runs as a Gradio front end on a free Hugging
Face Space: https://hamzaahmedsharif-docmind-service.hf.space/ (Space page:
https://huggingface.co/spaces/HamzaAhmedSharif/DocMind-Service). The front
end calls the real FastAPI app in-process (anonymous, public tenant) over
the seeded NIST demo corpus, with the demo configuration from
`deploy/release.env`. The service code is this repository at `21a1e3a`,
copied unchanged; only the front end is new, and one dependency pin
differs in the Space (`pydantic` 2.11.10; Gradio 5.49.1 requires < 2.12).
The P7.3 cross-encoder model (23 MB) is downloaded at Space startup
from the public Xenova repo — the Space uploader cannot carry it —
and verified by hash; if the download fails the Space runs dense-only
rather than failing to boot.
The Space sleeps when idle on the free tier and is capped at 300
questions/day by the same Postgres-backed demo cap as every other
instance. Verified live on 2026-11-07: an on-corpus question answered
with page citations, a novel on-corpus question generated live (1 LLM
call), and an off-corpus question refused (`low_evidence`). Verified
live again after the P7.3 re-sync (2026-11-14): a novel on-corpus
question answered with page citations (1 LLM call, cache miss) and
a repeat question served from the cache (0 calls). The demo is a
convenience for readers; the release verification above remains the
deployment evidence for the gated image. The decision and its recorded
reservations are in `DECISIONS.md`.

## Architecture

```mermaid
flowchart LR
  C[Client] -->|HTTPS| API[FastAPI service - 1 worker]
  API --> AUTH[auth + limits + guardrails]
  AUTH --> Q[answer_question - pure core]
  Q --> R[Retriever: PgStore]
  Q --> L[LLMClient: hosted adapter, throttled]
  R --> E[ONNX embedder - fastembed MiniLM-L6-v2]
  R --> X[Cross-encoder reranker - ONNX MiniLM-L-6-v2]
  R --> PG[(Postgres + pgvector)]
  AUTH --> CACHE[(semantic cache - same Postgres)]
  API --> M[/metrics + JSON logs/]
  L --> G[Groq free tier - gpt-oss-120b]
```

Components, data flows and the reason for each choice:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The engineering record, with
the alternatives that were rejected and why, is [`DECISIONS.md`](DECISIONS.md).

## Quality gates

Pre-registered in `evaluation/gates.json` before the first measurement and
generated into this table from the committed result files by
`scripts/sync_readme.py`; a test fails if the table drifts. What each gate
measures, the Project 6 comparison and the failure analysis:
[`docs/EVALUATION.md`](docs/EVALUATION.md).

<!-- BEGIN GENERATED: gates -->
| Gate | What it checks | Threshold | Measured |
|---|---|---|---|
| E1 | Embedding parity, min / mean cosine vs reference | >= 0.995 / >= 0.999 | 1.000 / 1.000 |
| E2 | Retrieval top-10 overlap vs the FAISS reference | >= 0.90 | 1.000 |
| E3 | Key facts in the retrieved context, d01-d12 | >= 23 / 26 † | 23 / 26 |
| S1 | Key facts in answers through the API, run A (run B) | >= 22 / 26 | 10 / 26 (16 / 26) - gate not met; analysis in docs/EVALUATION.md |
| S2 | Absent questions abstained, run A | >= 3 / 4 | 4 / 4 |
| S3 | Valid citations / answers with a citation, run A | >= 0.95 / >= 0.90 | 1.00 / 0.875 |
| S4 | Citations whose chunk supports the fact, run A | >= 0.75 target | 0.667 |
| S5 | Mean prompt tokens per answered query, run A | <= 3200 | 2002 |
| R1 | Injection attacks succeeding, guardrails on (off) | <= 2 / 15 | 0 / 15 (7 / 15) |
| C1 | Semantic-cache false-hit share, test half | <= 0.05 | 0.0000 |
| L1 | 5xx responses and OOM kills under the load matrix | 0 | 0 |
| MEM | Peak RSS under load, 512 MB container | <= 480 MB | 225.8 MB |

†: the E3 threshold was changed post-hoc from 24 to 23 (DECISIONS.md, 2026-11-03); the measured value is unchanged. S1 was not re-registered: the gate stands at 22 and the measured runs fall short, with the cause analysis in docs/EVALUATION.md.
<!-- END GENERATED -->

## Security and limits

The full threat table, test evidence and residual risks are in
[`docs/SECURITY.md`](docs/SECURITY.md). The short version, with the measured
numbers:

- **Keys and tenants:** `X-API-Key` is optional. A key is
  `dm_<8 hex>_<32 URL-safe chars>`; only the prefix and a SHA-256 hash are
  stored, and keys are revocable. Keyed tenants have isolated documents,
  per-key minute windows and daily caps, and document/page quotas. Anonymous
  callers are tenant `public`; anonymous uploads are blocked (403).
- **Limits:** anonymous demo 5 questions/minute per IP and 300/day; keyed
  tenants 30/minute and 200/day by default; a shared cap of 800 provider
  calls/day. The per-IP window is per process; the daily cap is stored in
  Postgres and shared across containers on the same database. Uploads are
  capped at 10 MB and 200 pages; 20 documents and 500 pages per key.
- **Guardrails:** prompt v2 treats retrieved text as untrusted, neutralizes
  fake citations and delimiter runs, and uses a canary. Citations the model
  invents are removed; an answer with no valid citation becomes an
  `ungrounded` refusal while `REQUIRE_CITATION` is on; Markdown images and
  URLs absent from the context are removed; long answers are truncated.
- **Red-team:** 15 poisoned passages, guardrails off vs on: **7 / 15**
  attacks succeeded with guardrails off, **0 / 15** with them on. The model
  itself resisted in the on arm; the deterministic filters were not the
  mechanism. `evaluation/results/redteam-m6.json`.
- **Evidence thresholds:** calibrated from retrieval only, per corpus:
  paper 0.35, demo 0.52. The threshold is per corpus and is not guessed.
- **Cache:** tenant-scoped semantic cache, threshold 0.86 from a pre-declared
  calibration/test split; test-half same-intent hit rate 0.3636, false-hit
  share 0.0000. Only non-refused, validated answers are stored.
- **Demo query log:** anonymous questions are stored redacted for 30 days
  (emails, phone numbers, ID-like numbers and links removed; names may
  remain). Keyed tenants are not logged. Do not enter personal data.
- **Not covered:** no WAF or bot protection, regex redaction misses names
  and novel formats, key revocation can take up to 60 s, and poisoned facts
  (plausible but wrong content) are out of scope.

Capacity on the free tiers — the provider's token limits, not the service,
bound the throughput: [`docs/CAPACITY.md`](docs/CAPACITY.md).

## Limits and known gaps

- **Service-level recall is lower than retrieval-level recall.** The gates
  above show E3 (facts present in the retrieved context) at 23 / 26 and S1
  (facts surviving into API answers) at 10 / 26 in run A and 16 / 26 in
  run B, against a pre-registered gate of 22. The measured causes are in
  `docs/EVALUATION.md`: fact chunks that fall below the evidence threshold
  never reach the prompt, and the all-or-nothing grounding refusal discards
  some answers whose facts were present. The threshold was not re-registered
  to hide this.
- **One paper.** All quality numbers are on *Attention Is All You Need*;
  nothing is claimed about other documents.
- **Single instance.** One worker, in-process per-IP limiter; the design
  targets free tiers, not horizontal scale (the load numbers with their
  conditions are in `docs/FACTS.md`).
- **Public demo is UI-only.** The Hugging Face Space exposes a Gradio
  front end, not the raw API, and sleeps when idle on the free tier
  (see Live demo).

Remediation (P7.1, 2026-11-07/08): after M8 the evidence gate was
conformed to the M6.4 spec (a top-1 test only — the shipped code had
filtered chunks one by one) and a citation-repair retry was added
(one retry, on an `ungrounded` outcome only). Measured after
remediation (post-hoc iteration, tuned on the evaluation questions):
run A2 met the S1 gate at 22/26 and run B2 measured 17/26 on identical
code, so the effect is smaller than run-to-run provider nondeterminism
on this set; the red-team re-check held at 0/15 with guardrails on.
Tuned on the same 12 questions; held-out check is Project 9. Full
numbers and the per-question record: `docs/EVALUATION.md`,
`DECISIONS.md`.

Remediation 2 (P7.2, 2026-11-09/10): the citation-repair retry was
made quote-anchored (quote the chunk lines verbatim first, then
answer citing them) and the prompt moved to p7-v3 with a
completeness instruction. A pre-run diagnostic fixed the honest
target: 23 of the 26 key facts are present in the retrieved
context. Measured after remediation (post-hoc iteration, tuned on
the evaluation questions): run A3 20/26 and run B3 21/26 — below
the ≥22 gate in both runs, and exactly 19 of the 23 reachable
facts in both runs; no document question was refused in either
run, and the remaining losses are retrieval rank, frozen-scorer
phrasing, and one omission. The red-team re-check held at 0/15
with guardrails on. Tuned on the same 12 questions; held-out
check is Project 9. Full numbers and the per-question record:
`docs/EVALUATION.md`, `DECISIONS.md`.

Retrieval unfrozen (P7.3, 2026-11-13/14): the owner decided to spend
Project 9's retrieval lever inside Project 7 — a local ONNX
cross-encoder reranker (dense top-25 reranked to top-10),
pre-registered with a free admissibility check (new ceiling 26/26,
memory 324 MB under a 512 MB limit, rerank p95 339 ms) and a final
stop rule. Measured after remediation (post-hoc iteration, tuned on
the evaluation questions): run A4 23/26 and run B4 24/26 — the S1
gate met in both runs; d02 and d09, the two questions the dense
top-10 could not ground, score full marks in both runs. S2 4/4 in
both runs, no safety regression, and the red-team re-check held at
0/15 with guardrails on. Tuned on the same 12 questions; held-out
check is Project 9. The reranker ships on. Full numbers and the
per-question record: `docs/EVALUATION.md`, `DECISIONS.md`.

## Quick start

Prerequisites: Docker, and Python 3.12 for the local checks.

```powershell
docker compose -f deploy/compose.ci.yml up --build --wait
$lines = docker compose -f deploy/compose.ci.yml exec -T app python -m docmind_service.admin create-key --tenant smoke-ci --label ci --write
$env:DOCMIND_SMOKE_KEY = $lines[[array]::IndexOf($lines, '-----BEGIN DOCMIND KEY-----') + 1]
python scripts\smoke_http.py --base http://127.0.0.1:8000 --mode ci --api-key-env DOCMIND_SMOKE_KEY
docker compose -f deploy/compose.ci.yml down -v
```

The smoke script exercises the write path, which requires an API key with
the write scope under the authentication rules in `docs/ARCHITECTURE.md`;
the middle lines create a throwaway key in the local stack for that
purpose, the same thing CI does.

```bash
curl -s http://127.0.0.1:8000/v1/query -H 'content-type: application/json' \
  -d '{"question": "What is self-attention?"}'
```

With the default fake provider the answer comes from the sample chunks; the
response carries citations, usage and a request id (also the `X-Request-ID`
header). To develop locally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1                      # lint, format, unit, contract
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Integration -Eval   # + DB/model tests + retrieval gates
```

After changing routes or schemas, run `python scripts/export_openapi.py`; a
test fails if `openapi.json` is out of date.

## Documents

- [`docs/EVALUATION.md`](docs/EVALUATION.md) — every gate, method and result,
  the Project 6 comparison, the recall curve, th