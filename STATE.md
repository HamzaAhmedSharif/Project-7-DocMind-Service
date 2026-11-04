# STATE
Updated: 2026-11-05 (overnight, Asia/Shanghai)
Current milestone: M7 · complete (L1 PASS, MEM PASS, drills verified; provider requests 0) — M7.8 live checks on the pushed head recorded below after the push
Last commit: HEADHASH
Last pushed head: HEADHASH · origin/main
Evidence branch: evidence/bad-chunking at 427d2c5 (unmerged)

## Milestones
| Milestone | Status | Verdict file | Commit | Date |
|---|---|---|---|---|
| M1 | done | — | 0e8a035 | 2026-10-30 |
| M2 | done | — | ddf8f69 | 2026-10-30 |
| P0 | done | reports/P0.md | af79b1d | 2026-11-03 |
| M3 | PASS-WITH-NOTES | reports/M3.md | 1538e20 (M3c) + FIX commits 992ee80 | 2026-11-03 |
| M4 | PASS-WITH-NOTES | reports/M4.md | beb6731, e1b816d, 123e697, ca18652, f4ecd92 | 2026-11-03 |
| M5 | PASS-WITH-NOTES (Amendment A1 Path C) | reports/M5.md | e5bfe5a | 2026-11-04 |
| M6 | PASS-WITH-NOTES | reports/M6.md | e3cfb2c | 2026-11-05 |
| M7 | complete — verdict in the manager's morning report | reports/M7.md | 46591eb, d410e3c, 472cc07, C4HASH | 2026-11-05 |

## M7 verification (2026-11-05, local, fake provider — 0 provider requests)
- **Load matrix** (`evaluation/results/load-m7.json`): 102,937 requests across the §9 matrix; every run HTTP 200, 0 timeouts, 0 OOM kills under `-m 512m`. Headline: unconstrained c10 mixed 113.6 rps, p95 0.107 s; soak 69,927 requests/600 s, memory 208.4 → 208.1 MB.
- **Gates, re-run by the manager on the committed JSON:** `check_gates.py --stage load` → L1 PASS (0); `--stage memory` → MEM PASS (225.8 ≤ 480).
- **Drills:** 1) DB down → 503 + `Retry-After: 30` + `retrieval_error`, recovery 2.3 s (first run exposed a 500 from the cache path — fixed, regression tests in `tests/test_db_down.py`); 2) provider down → 503 `provider_error`; 3) cap=1 → 200, 429 `daily_cap_reached` + `Retry-After`, refusal still 200; 4) cold start 1.69/1.77 s; 5) uploads 413/422/422/422, 204.7 MiB after. Drills 2/3/5 ran against an isolated drill database (the daily cap is Postgres-backed and shared).
- **Suite:** `pytest -q` 248 passed, 19 deselected; `ruff check .` clean.
- **M7.8 (Amendment A1 mapping):** M78TEXT

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
- None blocking M7 or M8.
- **Known non-blocking defect:** the laptop `.env.neon` still holds non-working values. It affects only future laptop-side Neon work; use the GitHub environment secrets or replace the laptop file. The CI path is unaffected.

## Post-hoc threshold changes
- E3 (M3): 24/26 → 23/26†, recorded in DECISIONS with the measured 23/26 and the pypdf-drift root cause.
- `MIN_EVIDENCE_SCORE = 0.2` (pre-M6) became the calibrated settings at M6: paper 0.35, demo 0.52; cache τ 0.86 by the pre-declared §8.7 selection rule (not post-hoc).

## Provider ledger (UTC)
- 2026-11-04 (M6 day): `used_today=76`, upper bound 80 of 800; M6-round calls 75 (attempts 112) of the 150-request M6 budget.
- 2026-11-05 (M7 day): M7 itself used **0** provider requests (fake provider for all load and drills). Release-smoke runs ≤ 1 request each.
- M8 budget ahead: ≤ 100 requests total, ≤ 60 per UTC day.

## Test coverage note
- `docmind_service/ratelimit.py` has dedicated unit tests in `tests/test_ratelimit.py` (7 tests: window math/Retry-After, key independence, eviction bound, client-IP spoof resistance, daily-cap rollover, `CappedLLM` increment order, no-evidence refusal not incrementing the cap). Not a gap.

## Notes for the next session
1. Next milestone: M8 (§10) — service-level evaluation with the real provider (≤100 requests), capacity model, held-out manifest, clean-clone rehearsal, review pack. M8's PASS closes Project 7.
2. M7 was completed by the manager after the free-model executor sessions failed (wrong directory, invented commits in a scratch repo — no harm; verified). The executor route stays suspended; see reports/M7.md "Execution note".
3. Known local-only test artifact: `test_query_log_failure_is_swallowed_and_leaks_no_text` can fail under local Windows pytest log capture; green in CI. Not M7-caused.
4. Deferred, non-blocking: manager's hands-on local re-runs for M3–M6 (deferred while laptop SSH was down; SSH restored 2026-11-05). [H10] metrics-token live check remains optional.

## Uncommitted (not this round)
- `evaluation/results/retrieval-local.json` — pre-existing untracked, never part of a milestone.
