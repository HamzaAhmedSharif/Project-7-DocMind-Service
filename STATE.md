# STATE
Updated: 2026-11-04 12:30 UTC
Current milestone: M6 · offline part + provider measurements complete; stopped before M6.10
Last commit: 6b51212 docs: record M6 provider measurements (no-citation, red-team R1) and ledger (local)
Last pushed head: c149900 · origin/main; M6 commits are local and not pushed
Evidence branch: evidence/bad-chunking at 427d2c5 (unmerged)

## Milestones
| Milestone | Status | Verdict file | Commit | Date |
|---|---|---|---|---|
| M1 | done | — | 0e8a035 | 2026-10-30 |
| M2 | done | — | ddf8f69 | 2026-10-30 |
| P0 | done | reports/P0.md | af79b1d | 2026-11-03 |
| M3 | done (manager released M4) | reports/M3.md | 1538e20 (M3c) + FIX commits 992ee80 | 2026-11-03 |
| M4 | built, pushed to origin/main; manager verdict not recorded | reports/M4.md | beb6731, e1b816d, 123e697, ca18652, f4ecd92 | 2026-11-03 |
| M5 | G8-C green; documents round complete; awaiting manager verdict | reports/M5.md | c149900 (pushed) + docs round (local) | 2026-11-04 |
| M6 | offline part + provider measurements measured; stopped before M6.10 | reports/M6.md | d62681d, a173df0, 66b87ea + measurement commit (local) | 2026-11-04 |

## M5 verification (Amendment A1)
- **G8-C:** release-smoke run 41809139449 (manual dispatch, head `c149900`), 9/9 PASS — https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41809139449.
- **Numbers** (GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt): `readyz_first_latency_s` 1.102, `first_query_latency_s` 1.98, `warm_query_latency_s` 0.556, `mem_peak_mib` 230.8. Stored in `evaluation/results/live-m5.json` (`variant: G8-C`).
- **M5.5 via CI:** neon-seed run 41807236461 — https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41807236461. Migrations `001_init`/`002_demo_caps` pre-applied by `AUTO_MIGRATE`; pgvector 0.8.6 on PostgreSQL 18.6; 3 documents / 639 chunks (128 + 168 + 343); database 7896 kB -> 11 MB; demo-check top-3 identical to the local reference.
- **Earlier release-smoke runs:** 41805063857 (`ac97221`) and 41807161569 (`c149900`) scored 7/9, failing only the two empty-corpus checks; provider requests 0 + 0 + 1 across the three runs.
- **CI runs:** 41804691328 (`ac97221`) and 41806745388 (`c149900`): all jobs success.
- **A1.8 documents:** README "Release verification"; `docs/FACTS.md` (new); `docs/EVALUATION.md` "Release verification" with the four non-proven items; `docs/OPERATIONS.md` release-smoke/neon-seed notes; DECISIONS main Amendment A1 entry.
- **Postgres major-version check:** integration + model tests once against `pgvector/pgvector:pg18` -> 10 passed, 128 deselected; PostgreSQL 18.6 / pgvector 0.8.7. Committed default stays pg17.

## [H] gates
| ID | What | Verification result | Status |
|---|---|---|---|
| H3 | Neon `.env.neon` | Resolved via CI: neon-seed run 41807236461 used the GitHub environment secrets; laptop `.env.neon` still holds non-working values (non-blocking) | resolved (CI path) |
| H4 | Render service URL | RETIRED under A1 (Render card wall 2026-11-04) | retired |
| H4a | GitHub environment `release-smoke` with three secrets | Used by the release-smoke and neon-seed runs; names only: `DOCMIND_DATABASE_URL`, `DOCMIND_DATABASE_URL_DIRECT`, `DOCMIND_LLM_API_KEY` | done |
| H5 | `DEMO_URL` + `RENDER_DEPLOY_HOOK_URL` | `RENDER_DEPLOY_HOOK_URL` retired; `DEMO_URL` conditional on a supplement passing (none) | retired/conditional |
| H6 | Groq key | Resolved: `check_llm` green (78 prompt / 28 completion, 4.010 s); configured key accepted for the M6 measurements (no-citation 12 questions, red-team 60 case-runs) | resolved |

## Blocked items
- None blocking M5.
- **Known non-blocking defect:** the laptop `.env.neon` still holds non-working values. It affects only future laptop-side Neon work; use the GitHub environment secrets or replace the laptop file. The CI path is unaffected.

## Post-hoc threshold changes
- `MIN_EVIDENCE_SCORE = 0.2` added in `query.py` so `zzzz qqqq` (top score 0.1818) refuses with `no_evidence`; M6 will make it a measured setting.

## Provider ledger today (UTC)
- Release-smoke runs today: 4 — counted by `provider_budget.py` from the workflow-run list (upper bound one request per run).
- Pre-flight (`provider_budget.py --used-today 24`, verbatim): `release_smoke_runs_today=4`, `used_today=24`, `used_today_upper_bound=28`.
- M6 measurement attempts (script output): `no_citation=1/12 recommended_default=True provider_requests=21`; red-team `provider_requests=39` (arm `off`) + `49` (arm `on`) = 88. Total 109.
- Post-flight (`provider_budget.py --used-today 133`, verbatim): `release_smoke_runs_today=4`, `used_today=133`, `used_today_upper_bound=137` of 800.
- M6-round attempts including the aborted pre-run (3 successful calls) and six auth-rejected attempts: 118, within the 150-request M6 budget.
- `evaluation/results/provider-limits.json` keeps the M5 `release_smoke` accounting block and adds the post-flight `m6_budget` block.

## Test coverage note
- `docmind_service/ratelimit.py` has dedicated unit tests in `tests/test_ratelimit.py` (7 tests: window math/Retry-After, key independence, eviction bound, client-IP spoof resistance, daily-cap rollover, `CappedLLM` increment order, no-evidence refusal not incrementing the cap). Not a gap.

## Notes for the next session
1. Manager: verdict on M6 (offline part + provider measurements; R1 PASS 0/15, no-citation 1/12 keeps `REQUIRE_CITATION=true`).
2. No push of the M6 commits; `c149900` is the pushed head.
3. M6.10 (Neon/live key checks, [H8]) is not started; no public host and no `DEMO_URL` per Amendment A1.
4. Provider budget: `used_today=133`, upper bound 137 of 800; M6-round attempts 118 of the 150-request M6 budget.
5. gitleaks full history and staged scan: no leaks found (verbatim in `reports/M5.md`).
6. `docs/FACTS.md` is new; every row cites a source file or run URL.

## Uncommitted (not this round)
- `evaluation/results/retrieval-local.json` — pre-existing untracked, not part of A1.
