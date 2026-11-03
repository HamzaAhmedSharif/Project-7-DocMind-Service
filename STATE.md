# STATE
Updated: 2026-11-03 15:02 UTC
Current milestone: M4 · step M4.9 · status awaiting manager verdict (blocked at [H1]/[H5]/[H7])
Last commit: M4: report and STATE · last code commit 123e697
Last pushed head: 992ee80 · CI run 41644978833 green (lint, test, secrets all success)
Local-only after the push: beb6731 (M4), e1b816d (docs), 123e697 (eval fix), evidence branch evidence/bad-chunking at 427d2c5 (unmerged), and the M4 report/STATE commit

## Milestones
| Milestone | Status | Verdict file | Commit | Date |
|---|---|---|---|---|
| M1 | done | — | 0e8a035 | 2026-10-30 |
| M2 | done | — | ddf8f69 | 2026-10-30 |
| P0 | done | reports/P0.md | af79b1d | 2026-11-03 |
| M3 | done (manager released M4) | reports/M3.md | 1538e20 (M3c) + FIX commits 992ee80 | 2026-11-03 |
| M4 | awaiting manager verdict | reports/M4.md | beb6731, e1b816d, 123e697; evidence 427d2c5 (unmerged) | 2026-11-03 |

## Pending [H] gates
| ID | What | Asked on | Status |
|---|---|---|---|
| H1 | Push the local M4 commits (beb6731, e1b816d, 123e697); confirm every CI job green (lint, unit, retrieval-eval, security, image, release) and record durations | 2026-11-03 | pending |
| H5 | GitHub settings: branch protection with required checks `lint`, `unit`, `retrieval-eval`, `security`, `image`; make the GHCR package public after the first `release` push; enable private vulnerability reporting (SECURITY.md refers to it) | 2026-11-03 | pending |
| H6 | `DOCMIND_LLM_API_KEY` missing → `scripts\check_llm.py` prints `PENDING-H6`; manager must complete before M5/M8 | 2026-11-03 | pending |
| H7 | Push `evidence/bad-chunking` (427d2c5), open the PR, do not merge; the workflow comments the gate table; then fill "Gate demonstration" in docs/EVALUATION.md (PR URL, failing run URL, E2/E3 values) and commit `docs: gate demonstration`; close the PR with a one-line comment | 2026-11-03 | pending |

## Blocked items
- [H1]/[H5]/[H7] as above; the executor performed no push and changed no GitHub settings.
- H6: LLM API key not configured; `check_llm.py` prints `PENDING-H6`, exit 0. No provider call made.

## Post-hoc threshold changes
- E3 retrieval gate — COMPLETED 2026-11-03 (Hamza, Class C via the manager): threshold changed 24 → 23 of 26. `evaluation/gates.json` records the change in `post_hoc_changes`; `evaluation/check_gates.py --stage retrieval` now reports E3 `23 / 26 | >= 23 | PASS`. Measured value unchanged at 23/26. Cause proven by Manager FIX-1: pypdf 6.x token spacing vs P6's pypdf 5.0.1 shifted the d02 scaling sentence across the chunk 10/11 boundary; retrieval parity E2 = 1.000, E1 mean = 1.0. † marks in `reports/M3.md`; full entry and chronology notes in `DECISIONS.md`.

## Provider ledger today (UTC): 0 of 800 (combined cap)

## Notes for the next session
- M4 is built and verified locally. `scripts\check.ps1 -Integration -Eval`: ruff clean, `103 passed` unit, `9 passed` integration/model, contract clean, E1 min/mean = 1.000000, E2 = 1.000, E3 = 23/26 PASS.
- Image `docmind-service:local`: 987,185,947 bytes, uid 10001, offline model test `(384,) 1.0`; base digest `python@sha256:e697c818…`; plain build 63.4 s (no mirror needed after the network recovered).
- Trivy 0.76.0: blocking scan (CRITICAL with a fix) exit 0; report scan 38 findings (36 HIGH, 2 CRITICAL, both unfixed in Debian bookworm). pip-audit 2.10.1 on the lock: "No known vulnerabilities found". actionlint 1.7.7: exit 0. No `<pinned` left in ci.yml.
- Container measurements in `evaluation/results/m4-container.json`: startup 6.7 s, idle 202.4 MB, 202.1 MB after 100 queries, `OOMKilled` false in a 512 MB / 0.5 CPU container. Memory ladder not needed.
- Evidence branch `evidence/bad-chunking` (427d2c5): `CHUNK_WORDS = 800`, `default_top_k = 4`, unit tests updated; G1/G2/G3 pass; E2 = 0.080 FAIL (gate blocks), E3 = 26/26 PASS — the script predicted E3 to fail too; recorded as a deviation in reports/M4.md. Do not merge.
- Network (R5): Docker Hub and Hugging Face were unreachable at the start; two Docker Hub mirrors returned the same base digest and a direct pull later confirmed it; one build used the documented `HF_ENDPOINT` build argument and the final build was plain. Nothing mirror-related is committed. The `# syntax=` Dockerfile line was removed (frontend image needs Docker Hub; no dockerfile-1.x feature used).
- `evaluation/run_retrieval.py` now reports E1 chunk parity as `null` when the chunk count diverges instead of crashing (commit 123e697); main-branch numbers unchanged.
- Pinned gitleaks 8.24.3 over the full history after the M4 commits and the evidence commit: `16 commits scanned`, `no leaks found`, `EXIT=0`. `.gitleaksignore` unchanged.
- Next actions are Hamza's: [H1] push, [H5] settings, [H7] evidence PR and the `docs: gate demonstration` commit.
