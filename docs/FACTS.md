# Facts

Every public number with its source and conditions. A number quoted without its conditions is not a claim this project makes. Format: `Fact | Value | Definition and conditions | Source file | Commit | Date`.

| Fact | Value | Definition and conditions | Source file | Commit | Date |
|---|---|---|---|---|---|
| Release image commit identity | label = pushed commit = `/healthz` commit (`c149900`) | release-smoke run 41809139449; image built with `--build-arg GIT_SHA=<commit>` and `org.opencontainers.image.revision` label | `evaluation/results/live-m5.json` | c149900 | 2026-11-04 |
| Readiness latency (first `/readyz`) | 1.102 s | GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt | `evaluation/results/live-m5.json` | c149900 | 2026-11-04 |
| First query latency | 1.98 s | GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt | `evaluation/results/live-m5.json` | c149900 | 2026-11-04 |
| Warm query latency | 0.556 s | GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt | `evaluation/results/live-m5.json` | c149900 | 2026-11-04 |
| Peak memory | 230.8 MiB | GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt; sampled during the run | `evaluation/results/live-m5.json` | c149900 | 2026-11-04 |
| Demo corpus | 3 documents / 639 chunks (128 + 168 + 343) | Neon free plan, PostgreSQL 18.6; NIST AI 100-1, AI 600-1, AI 100-2; Neon top-3 results identical to the local reference file | `evaluation/results/demo-questions-check.json` | c149900 | 2026-11-04 |
| Database engine | pgvector 0.8.6 on PostgreSQL 18.6 | Neon free plan; verified in the neon-seed run | neon-seed run 41807236461 | c149900 | 2026-11-04 |
| Database size after ingest | 11 MB (from 7896 kB) | Neon free plan; 3 documents / 639 chunks | neon-seed run 41807236461 | c149900 | 2026-11-04 |
| G8-C release-smoke run | success, 9/9 checks | manual dispatch, head `c149900`; GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt | https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41809139449 | c149900 | 2026-11-04 |
| Hosting status | public UI demo on a free Hugging Face Space (ZeroGPU); raw API not exposed | Gradio front end over the service code at `79c596a`, anonymous public tenant, seeded NIST demo corpus; created 2026-11-07 on the owner's instruction, after every free container host checked on 2026-11-04 either required a card or restricted the runtime | https://huggingface.co/spaces/HamzaAhmedSharif/DocMind-Service | 79c596a | 2026-11-07 |
| Public demo verification | cited answer (cache hit, pp. 24-25) + live-generated cited answer (1 LLM call, 388 prompt tokens, p. 30) + off-corpus refusal `low_evidence` | asked anonymously through the live Space's Gradio API, 2026-11-07 | https://hamzaahmedsharif-docmind-service.hf.space/ | 79c596a | 2026-11-07 |
| Public demo deltas vs release config | `DOCMIND_DEMO_IP_PER_MIN` 60 (release: 5); pydantic 2.11.10 (repo: 2.14.1) | Space-only adaptations, disclosed in the Space README: all UI traffic shares one in-process client bucket; Gradio 5.49.1 requires pydantic < 2.12; daily caps unchanged (300 anonymous / 800 global, Postgres-backed) | Space repository `app.py`, `requirements.txt` | 79c596a | 2026-11-07 |
| A1.6 free-host probes | not run | optional supplement probes were not executed; no host was tested | this file | — | 2026-11-04 |
| API-key format and storage | `dm_<8 hex>_<32 URL-safe chars>`; prefix + SHA-256 only | offline unit/integration tests; full key shown once and never stored | `docmind_service/auth.py`, `tests/test_auth.py` | — | 2026-11-04 |
| Tenant isolation | two keys, same PDF -> two documents | offline API isolation matrix; list/delete/query/document filter; SQL cache/auth integration tests | `tests/test_tenancy.py`, `tests/test_m6_integration.py` | — | 2026-11-04 |
| Rate limits | demo 5/min + 300/day; key 30/min + 200/day; global 800/day | offline tests; limiter state is per process | `docmind_service/config.py`, `tests/test_tenancy.py` | — | 2026-11-04 |
| Quota failure | 403 `quota_exceeded` | document and page quotas; SQL and in-memory stores | `tests/test_tenancy.py`, `tests/test_m6_integration.py` | — | 2026-11-04 |
| Redaction recall | 51/51 = 1.000 | synthetic PII set; threshold at least 95% | `tests/redaction_cases.json`, `tests/test_redaction.py` | — | 2026-11-04 |
| Redaction benign false positives | 0/18 | benign numbers must not change; threshold at most 2 | `tests/redaction_cases.json`, `tests/test_redaction.py` | — | 2026-11-04 |
| Evidence threshold, paper | 0.35 | min answerable top-1 0.3737 (d07) - 0.02, floored; 0/4 absent questions below it | `evaluation/results/evidence-m6.json` | — | 2026-11-04 |
| Evidence threshold, demo | 0.52 | min answerable top-1 0.5465 (d06) - 0.02, floored; 6/6 off-topic questions below it | `evaluation/results/evidence-m6-demo.json` | — | 2026-11-04 |
| Cache calibration | tau 0.86; test hit rate 0.3636; test false-hit 0.0000 | 44 same-intent + 32 different-intent probes; odd calibration / even test; selection on calibration only | `evaluation/results/cache-m6.json` | — | 2026-11-04 |
| Red-team R1 | arm `on` 0/15; arm `off` 7/15 | 15 poisoned passages, 2 repeats per arm; live run 2026-11-04; gate R1 `0 / 15 <= 2` PASS (not gating) | `evaluation/results/redteam-m6.json` | — | 2026-11-04 |
| No-citation policy | 1/12 answers without a valid citation; 0/12 refused; `REQUIRE_CITATION` stays `true` | 12 answerable paper questions with the citation check off; pre-declared rule keeps the default only if at most 1 of 12 would become a refusal | `evaluation/results/no-citation-m6.json` | — | 2026-11-04 |
| Demo query-log retention | 30 days, anonymous tenant only | redacted text, at most 500 characters; keyed tenants get no row | `docmind_service/querylog.py`, `tests/test_redaction.py` | — | 2026-11-04 |
| M6.10 live key check (local) | 9/9 PASS | release image commit `703a842` run locally with a local database, `DOCMIND_UPLOADS_ENABLED=true` for the local run only; `$env:DOCMIND_SMOKE_KEY`; PASS/FAIL for bad key 401, list 200, upload 201, duplicate 200, query 200 with citation, repeat `cache=="hit"`, delete 204, list document gone, anonymous upload 403 | `scripts/live_key_check.ps1`, local `http://127.0.0.1:8000` | 703a842 | 2026-11-04 |
| M6.10 manager checks (local, anonymous) | sample 200 + citations; off-topic `low_evidence`, daily counter 1→1; rate-limit headers on `/v1/query`; `query_log` rows present; `show-log --last 3` redacted only (`[EMAIL]` for a test email) | run against the same local release image; no Neon, no `DEMO_URL`, no live demo claimed | local `http://127.0.0.1:8000`, `docmind-pg` container | 703a842 | 2026-11-04 |
| Release config calibrated demo values | evidence 0.52, cache true, threshold 0.86, require_citation true; uploads false | `deploy/release.env` aligned to `evaluation/results/evidence-m6-demo.json` and `cache-m6.json`; `DOCMIND_UPLOADS_ENABLED=false` stands (A1.3) | `deploy/release.env` | 703a842 | 2026-11-04 |
| M7 load matrix | 102,937 requests; every run HTTP 200; 0 timeouts; 0 OOM kills | §9 matrix (unconstrained + render-like profiles, mixed + answered, 600 s soak) under `-m 512m`, fake provider, demo corpus as tenant `public` | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| L1 (load gate) | 0 | no 5xx and no OOM at concurrency ≤ 10, checked by `check_gates.py --stage load` on the committed matrix record | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| MEM (M7 memory gate) | peak 225.8 MB | highest per-run peak across the matrix under `-m 512m`, checked by `check_gates.py --stage memory` against the 480 MB threshold | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| Unconstrained throughput | 121.3 rps at c5; 113.6 rps at c10 (mixed) | fake provider; plateau beyond c5 is embedding-CPU-bound | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| Render-like throughput (0.1 CPU) | 12.8 / 5.8 / 4.7 rps at c1 / c5 / c10; p95 0.11 / 1.90 / 4.00 s | degrades in latency only: zero errors or OOM at every level | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| Soak | 69,927 requests in 600 s at c5; memory 208.4 MB at 1 min → 208.1 MB at end | flat memory, within the +10% rule | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| Cache-on answered run | 139.6 rps, p95 0.091 s | answered-only at c10 with the semantic cache on | `evaluation/results/load-m7.json` | 472cc07 | 2026-11-05 |
| Container image (M7) | 988,656,797 bytes | +1,470,850 bytes vs M4 (987,185,947) — the prometheus_client dependency | `docker inspect docmind-service:m7` | 46591eb | 2026-11-05 |
| Drill 1 — database down | query 503 with `Retry-After: 30`, outcome `retrieval_error`; recovered 2.3 s after the database restarted, no app restart | first run exposed a 500 (cache path did not translate database errors); fixed with regression tests | `tests/test_db_down.py`, `docs/OPERATIONS.md` | 46591eb | 2026-11-05 |
| Drill 2 — provider down | query 503, outcome `provider_error` | hosted provider pointed at a dead base URL; isolated drill database | `docs/OPERATIONS.md` | 472cc07 | 2026-11-05 |
| Drill 3 — daily cap 1 | q1 200 answered; q2 429 `daily_cap_reached` with `Retry-After`; low-evidence question still refused 200 | isolated drill database, release evidence threshold 0.52 | `docs/OPERATIONS.md` | 472cc07 | 2026-11-05 |
| Drill 4 — cold start | `/healthz` 1.69 s, `/readyz` 1.77 s | local container, release image | `docs/OPERATIONS.md` | 472cc07 | 2026-11-05 |
| Drill 5 — uploads | 413 / 422 / 422 / 422 (11 MB / not-a-PDF / fake-encrypted / empty); 204.7 MiB after | keyed uploads via the `X-API-Key` header; isolated drill database | `docs/OPERATIONS.md` | 472cc07 | 2026-11-05 |
| Provider requests in M7 | 0 | all load and drill evidence used the fake provider (drill 2 pointed the hosted provider at a dead local address) | `reports/M7.md` | 472cc07 | 2026-11-05 |
| Service eval S1, run A | 10 / 26 key facts | shipped configuration (evidence 0.35, citations required, guardrails on), local image `docmind-service:m8` at 512 MB, fresh eval database, paper uploaded through the API (49 chunks); merged record: the original run crossed a transient provider 503 cluster and 5 questions were re-run under the failure rule (d08 a provider casualty, 503 on three attempts) | `evaluation/results/service-eval-m8.json` | 0694bc4 | 2026-11-06 |
| Service eval S1, run B | 16 / 26 key facts | same conditions as run A; no provider failures in this run | `evaluation/results/service-eval-m8.json` | 0694bc4 | 2026-11-06 |
| Service eval S2 | 4 / 4 abstentions in both runs | absent questions a01–a04; abstention = refused flag or a Project 6 abstention pattern | `evaluation/results/service-eval-m8.json` | 0694bc4 | 2026-11-06 |
| Service eval S3 | valid-citation share 1.000 in both runs; answers-with-citation 0.875 (A) / 1.000 (B) | citations validated against the eval database; the validator's invalid-citation counter moved by 0 in both runs | `evaluation/results/service-eval-m8.json` | 0694bc4 | 2026-11-06 |
| Service eval S4 | 0.667 (A) / 0.875 (B) | share of found key facts whose cited chunk contains the fact's pattern | `evaluation/results/service-eval-m8.json` | 0694bc4 | 2026-11-06 |
| Service eval S5 | mean prompt tokens 2002 (A) / 2351 (B) | answered and refused queries both counted; ceiling 3200 | `evaluation/results/service-eval-m8.json` | 0694bc4 | 2026-11-06 |
| S1 shortfall decomposition | evidence gate 5 facts (d07, d09); grounding refusals 4 facts (d03, d11); partial answer 1 fact (d12) | offline retrieval probe against the eval database with the app's own embedder; zero provider calls; refused drafts are not returned by the API, so the validator mechanism is inferred from refusal reasons | `docs/EVALUATION.md` | 0694bc4 | 2026-11-06 |
| Capacity: provider-bound throughput | 2.88 queries/minute; 80.0 answered queries/day | Groq free plan (TPM 8,000, TPD 200,000) at the measured 2,498.9 tokens per answered query; min(RPD 1000, global cap 800, TPD / tokens) | `evaluation/results/capacity-m8.json` | 9f042e4 | 2026-11-06 |
| Capacity: served per day scenarios | 80.0 (cache 0) / 125.8 (cache 0.3636) / 160.1 (cache 0.5) | the 0.3636 rate is the M6 probe-set measurement, labelled a scenario, not traffic | `evaluation/results/capacity-m8.json` | 9f042e4 | 2026-11-06 |
| Held-out manifest | 24 papers: 8 each cs.CL, cs.IR, cs.LG, submitted from 2026-01-01 in submission order, 6–25 pages, ≥ 500 extractable chars/page | selection procedure fixed in advance, no cherry-picking; PDFs kept out of git; model documented knowledge cutoff 2024-06 | `evaluation/heldout/manifest.json` | 9f042e4 | 2026-11-06 |
| M8 provider requests, 2026-11-06 | 45 at commit time; the day closed at 83 — see the budget incident row below | check_llm 1, run A 11, run A repairs 5, d08 retry 0, run B 28; milestone cap 100, day cap 60 | `reports/provider-ledger.csv` | 0694bc4 | 2026-11-06 |

| S1 run C (ablation) | 19 / 26 — a lower bound: d10 and d11 (4 facts) returned provider 503 on all three attempts | guardrails off (`DOCMIND_GUARDRAILS_ENABLED=false`), same stack, model and questions | `evaluation/results/service-eval-m8.json` | b1dea68 | 2026-11-07 |
| S2 run C | 2 / 4 recorded; a02 and a03 unmeasurable (503 on every attempt) and count as non-abstentions; both measured absent questions (a01, a04) abstained | ablation configuration | `evaluation/results/service-eval-m8.json` | b1dea68 | 2026-11-07 |
| S3b / S4 / S5 run C | 0.625 / 0.700 / 1741 mean prompt tokens | citations not required in the ablated configuration | `evaluation/results/service-eval-m8.json` | b1dea68 | 2026-11-07 |
| Manager checkpoint re-runs | d01 reproduced 2 / 2 facts and a01 reproduced its abstention through the local image, matching run A | run A configuration; 2 provider requests | `reports/provider-ledger.csv` | b1dea68 | 2026-11-07 |
| Budget incident | a leftover one-shot scheduled task re-executed runs A and B overnight (2026-11-06 23:59): +38 requests; the day-cap accounting and the recovery are recorded in `DECISIONS.md` | duplicate measurements discarded; canonical A / B restored from the committed results file | `reports/provider-ledger.csv` | b1dea68 | 2026-11-07 |
| M8 provider requests, total | 97 by the ledger — 2026-11-06: 83 including the 38 duplicate-run requests; 2026-11-07: 14 (run C 4, C repairs 5 + 3, checkpoint 2). Release-verification runs spend 1 request each and are reported with the release track, as at M7 | caps: 100 for the milestone (met), 60 per day (exceeded on 2026-11-06 — see the incident row) | `reports/provider-ledger.csv` | b1dea68 | 2026-11-07 |

| Live verification on the final code head | release-smoke success, 9/9 checks, commit `617f16d`, 2026-11-07 | GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt; 1 provider request | https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/42343057863 | 617f16d | 2026-11-07 |
| Clean-clone rehearsal | PASS-WITH-NOTES: the README quick start (compose up, throwaway key, smoke) passes 14/14 from a fresh clone of the final head; the fresh-venv leg cannot install the locked environment on Windows because `requirements.lock` pins `uvloop`, which does not support Windows — the service targets Linux, where CI and Docker are green | rehearsals 2026-11-06/07; the earlier attempts' failures were hotspot connection resets and a Windows pytest tmpdir artifact, both recorded in `reports/REVIEW-PACK.md` | `reports/REVIEW-PACK.md` | 617f16d | 2026-11-07 |

## Allowed claims

Sentences this project may make, because each is backed above:

- "A production-style RAG service on free tiers, with API keys, guardrails and a semantic cache, verified in CI against managed Postgres and the real provider."
- "Retrieval puts 23 of 26 key facts in the top-10 context on the evaluation paper; end-to-end answers carry 10–16 of 26, and the gap is measured and explained."
- "On 15 poisoned passages, no attack succeeded with guardrails on and 7 succeeded with them off."
- "Under the M7 load matrix the service answered 102,937 requests with no 5xx and no OOM kill in a 512 MB container (fake provider)."
- "On the provider's free plan, the token limits bound the service to about 80 answered queries a day at the measured prompt size."

## Forbidden claims

<!-- claims-check-ignore-start -->
- "production-grade", "enterprise-grade", "state-of-the-art", and unqualified "secure" or "safe" — enforced by `scripts/check_claims.py` over the README and docs.
<!-- claims-check-ignore-end -->
- Any accuracy claim for multi-agent answering in this service (not implemented; the capacity model's multi-agent rows are derived from Project 6 and labelled as such).
- Any retrieval or answer-quality claim about documents other than the one evaluated paper.
- "Deployed" for the API without a green release-verification run linked in the same file; the public demo is a UI front end on a free Space, not the raw API, and is never described as the gated image running.

Numbers that must not be used without their conditions:

- **23 / 26** — retrieval-level (facts present in the top-10 context), one paper, threshold changed post-hoc from 24 (dagger everywhere it appears).
- **0 / 15** — 15 poisoned passages, guardrails on, and the model itself resisted; the deterministic filters were not the mechanism.
- **121 rps** — fake provider, unconstrained local container; the render-like profile at concurrency 10 is 4.7 rps.
- **80 answered queries/day** — the provider free plan's token cap at the measured prompt size, not a service limit.
- **92.3%** — Project 6's tuned retrieval recall; this service's retrieval point is 23 / 26 (88.5%) and its answer-level figures are S1 above.
