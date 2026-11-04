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
| Hosting status | no persistent public instance | no persistent host; every free container host checked on 2026-11-04 either required a card or restricted the runtime | `docs/OPERATIONS.md` | c149900 | 2026-11-04 |
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
