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
