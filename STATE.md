# STATE
Updated: 2026-11-04 08:13 UTC
Current milestone: M5 · Amendment A1 (A1.1–A1.5) done; M5.5 gated on H3; A1.4 9/9 (was 8/9 gated on H6; H6 resolved)
Last commit: d5cae39 M5.3: strip zero-width chars before citation parsing (local only)
Last pushed head: f4ecd92 docs: gate demonstration · origin/main; local main is ahead of origin/main; no push performed
Evidence branch: evidence/bad-chunking at 427d2c5 (unmerged)

## Milestones
| Milestone | Status | Verdict file | Commit | Date |
|---|---|---|---|---|
| M1 | done | — | 0e8a035 | 2026-10-30 |
| M2 | done | — | ddf8f69 | 2026-10-30 |
| P0 | done | reports/P0.md | af79b1d | 2026-11-03 |
| M3 | done (manager released M4) | reports/M3.md | 1538e20 (M3c) + FIX commits 992ee80 | 2026-11-03 |
| M4 | built, pushed to origin/main; manager verdict not recorded | reports/M4.md | beb6731, e1b816d, 123e697, ca18652, f4ecd92 | 2026-11-03 |
| M5 | A1.1–A1.5 done (amended scope); M5.5 gated on H3; A1.4 9/9 | reports/M5.md | d5cae39 (A1 complete incl. zero-width fix) | 2026-11-04 |

## A1.1–A1.5 (Amendment A1, this round) — commits
- `19de4dd` M5.1/M5.3: demo guard, landing page, citation parsing
- `55895c6` M5.2: NIST demo corpus, ingest and retrieval check
- `2f2e975` A1.1: retire Render; document hosting options and release image
- `8bad732` A1.2: bake the commit into the release image
- `4db5621` A1.3: non-secret release configuration
- `4c38eb8` A1.4: nine-check ephemeral release smoke
- `7deeda4` A1.5: release-smoke workflow and local runners
- `d5cae39` M5.3: strip zero-width chars before citation parsing (A1.4 check-6 fix)

## Pending [H] gates
| ID | What | Verification result | Status |
|---|---|---|---|
| H3 | Neon project and `.env.neon` with `DOCMIND_DATABASE_URL` (pooled) and `DOCMIND_DATABASE_URL_DIRECT` (direct) | `.env.neon` present with exactly the two lines. Pooled: `CONNECT_OK PostgreSQL 18.6`. Direct: `CONNECT_FAIL OperationalError auth_failed=True` — M5.5 gated | pending |
| H4 | Render service URL | No service URL; no push; release-smoke cannot run remotely | pending (blocked by no-push) |
| H5 | GitHub variable `DEMO_URL` and secret `RENDER_DEPLOY_HOOK_URL` | `gh variable list` and `gh secret list` empty, exit 0; no org account (404); zero repo environments | pending |
| H6 | Groq key in local `.env` | RESOLVED: first live `check_llm` HTTP 403 `Forbidden` (`PermissionDeniedError`, exit 1) was transient; retry green — 78 prompt / 28 completion tokens, 4.010 s, `CHECK_LLM_EXIT=0` | resolved |

## Blocked items
- **M5.5 Neon migrate/ingest/check:** direct URL `DOCMIND_DATABASE_URL_DIRECT` fails `OperationalError auth_failed=True`; pooled URL works but cannot run `pg_advisory_lock` migrations. Gated on H3 (Hamza: replace with a valid direct Neon string; values never pasted).
- **Push authorization:** local `main` is ahead of `origin/main` (`f4ecd92`); no push performed per standing instruction. Authorize push so `release-smoke` can run against Neon.
- **`provider_budget.py` run count:** GitHub API `HTTPError` (needs auth/public repo); workflow never ran, 0 by observation.

## Post-hoc threshold changes
- `MIN_EVIDENCE_SCORE = 0.2` added in `query.py` so `zzzz qqqq` (top score 0.1818) refuses with `no_evidence`; M6 will make it a measured setting.

## Provider ledger today (UTC)
- Provider requests: 2 successful of 800 (78 prompt / 18 completion earlier; 78 prompt / 28 completion on retry). `check_llm.py` made no successful call on the 403 attempt.
- release-smoke runs: 0 (workflow never ran; no push).

## Notes for the next session
1. Hamza: provide `[H3]` `.env.neon` with a valid direct Neon string (two lines, values never pasted), `[H4]` Render service URL, `[H5]` `DEMO_URL` + `RENDER_DEPLOY_HOOK_URL`.
2. Manager: authorize a push of the finished M5/A1 commits before the live check; `origin/main` is still `f4ecd92`.
3. Executor: M5.5 is gated on H3; once H3 is provided, run `python -m docmind_service.db migrate --env-file .env.neon`, `python -m docmind_service.db status --env-file .env.neon`, `python scripts/ingest_corpus.py --manifest evaluation/demo_corpus.json --tenant public --env-file .env.neon`, `python -m docmind_service.db status --env-file .env.neon`, `python scripts/check_demo_corpus.py --env-file .env.neon`.
4. Then M5.6–M5.10 exactly as section 7; G8 is report-level, and the word "deployed" is not used until G8 is green.
5. gitleaks 8.24.3 ran over full history and staged diff at every commit gate; both report "no leaks found" (verbatim outputs in `reports/M5.md`). `git ls-files` shows only `.env.example` under `.env*`.
6. `smoke.json`, `mem.txt`, `data/`, `.env*`, `STATE.md`, `reports/` are gitignored; `STATE.md`/`reports/` are tracked, use `git add -f`.

## Uncommitted (not this round)
- `evaluation/results/retrieval-local.json` — pre-existing untracked, not part of A1.
