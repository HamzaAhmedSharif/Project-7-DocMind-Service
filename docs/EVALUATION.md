# Evaluation and quality gates

Every claim in this repository is backed by a number produced by the code in
`evaluation/` and checked against the pre-registered thresholds in
`evaluation/gates.json`. The gates file was committed before the first measurement;
changing a threshold requires a "Post-hoc threshold change" entry in `DECISIONS.md`
and a dagger (†) on every table row that uses it. There is one such change so far
(E3, 24 → 23, see `DECISIONS.md`).

## Gates in words

| Gate | Stage | What it measures | Threshold | Gating | Status |
|---|---|---|---|---|---|
| E1_min | retrieval | Lowest cosine similarity between the service's embeddings and the reference vectors (embedding parity) | ≥ 0.995 | no | measured (M3) |
| E1_mean | retrieval | Mean cosine similarity against the reference vectors | ≥ 0.999 | no | measured (M3) |
| E2 | retrieval | Mean share of the reference top-10 chunks that the service also returns in its top-10, over all 20 questions | ≥ 0.90 | **yes** | measured (M3) |
| E3 | retrieval | Key facts found in the retrieved context for the 12 document questions (26 facts total) | ≥ 23 / 26 † | **yes** | measured (M3) |
| S1 | service_eval | Key facts found end-to-end through `POST /v1/query` | ≥ 22 / 26 | **yes** | measured (M8): run A 10 / 26, run B 16 / 26 — gate not met |
| S2 | service_eval | Absent-topic questions answered with an abstention | ≥ 3 / 4 | **yes** | measured (M8): 4 / 4 in both runs |
| S3a | service_eval | Citations that point at a chunk that exists | ≥ 0.95 | no | measured (M8): 1.000 in both runs |
| S3b | service_eval | Answers that carry at least one citation | ≥ 0.90 | no | measured (M8): run A 0.875, run B 1.000 |
| S4 | service_eval | Citations whose chunk supports the quoted fact | ≥ 0.75 | no | measured (M8): run A 0.667, run B 0.875 |
| S5 | service_eval | Mean prompt tokens per query (cost ceiling) | ≤ 3200 | no | measured (M8): run A 2002, run B 2351 |
| R1 | redteam | Attacks that succeed with guardrails on | ≤ 2 / 15 | no | M6 |
| C1 | cache | Wrong answers served from the semantic cache | ≤ 0.05 | **yes** | M6 |
| L1 | load | 5xx responses and OOM kills under the load test | == 0 | **yes** | M7 |
| MEM | memory | Peak RSS of the service under load, in a 512 MB container | ≤ 480 MB | **yes** | M7 |

E1, E2 and E3 run in CI on every push and pull request (`retrieval-eval` job);
a red gate blocks the merge. The service-level gates (S*, R1, C1, L1, MEM) are
pre-registered here and get their first measurements in M6–M8. M4 records a
first memory reading (idle and after 100 queries) in
`evaluation/results/m4-container.json`.

## Reference fixtures

`evaluation/fixtures/` holds three committed files (~110 KB of vectors, no text):

- `reference_chunk_vectors.npy` — 49 × 384 float32 embeddings of the corpus chunks.
- `reference_question_vectors.npy` — 20 × 384 float32 embeddings of the questions.
- `reference_top10.json` — for every question, the 10 chunk ordinals returned by a
  FAISS exact search over the reference chunk vectors.

They were built by `scripts/reference/make_reference.py`, run once with Project 6's
`rag` environment (`sentence-transformers` 3.2.1, `faiss` 1.9.0; versions in
`reference_meta.json`). The script encodes the same `data/work/chunks.json`
produced by this repository's chunker (49 chunks at 150 words / 25 overlap) and
the same 20 questions from `evaluation/questions.py` (12 document questions,
4 web questions, 4 absent-topic questions), then writes the three files above.
The corpus is *Attention Is All You Need* (`evaluation/corpus.json`, sha256
`bdfaa68d…`), downloaded by `scripts/fetch_corpus.py` and pinned by hash.

E1 compares the service's own embeddings with the reference vectors. E2 compares
the service's top-10 chunk ordinals with the reference top-10. E3 checks, for the
12 document questions, whether the retrieved context contains each expected key
fact, using the normalising scorer in `evaluation/scoring.py`.

## Reproduce locally

Prerequisites: Docker running (for Postgres with pgvector) and the main
environment (`B:\Applications\MiniConda\envs\docmind-service\python.exe`, as the
script is written for this machine).

```powershell
# Start the dev database (same settings as the M3 docker run)
docker compose -f deploy/compose.dev.yml up -d

# Everything CI runs, plus integration/model tests and the retrieval gates
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Integration -Eval
```

Without options, `scripts\check.ps1` runs exactly the fast CI checks: `ruff check`,
`ruff format --check`, the unit tests and the OpenAPI contract-drift check.
`-Integration` adds the integration and model tests against
`DOCMIND_TEST_DATABASE_URL` (default
`postgresql://postgres@127.0.0.1:5433/docmind_test`). `-Eval` runs
`evaluation.run_retrieval` and then `evaluation.check_gates`; the gate table is
printed and the machine-readable results land in
`evaluation/results/retrieval-local.json`.

The evaluation uses the shipped defaults on purpose: chunk parameters come from
`docmind_service.chunking` (`chunk_pages` defaults) and the top-k from
`Settings().default_top_k`. `tests/test_eval_defaults.py` fails if the runner
starts hard-coding its own values again.

In CI the same numbers are produced by the `retrieval-eval` job with
`--label ci`; the gate table is commented on the pull request and uploaded as
the `retrieval-results` artifact.

## Gate demonstration

The evidence PR is a deliberately plausible "optimization" on branch
`evidence/bad-chunking`: `CHUNK_WORDS = 800` in `docmind_service/chunking.py` and
`default_top_k = 4` in `docmind_service/config.py`, with the unit tests updated
so only the evaluation gates can object. It exists to prove that the same
change that cost Project 6 31 percentage points (92.3% → 61.5% key-fact recall)
is stopped at review time here, not discovered after deployment.

Completed 2026-11-03. Pull request: https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/pull/8 — failing run: https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41664131689. The gate table posted on the PR by CI reads: E2 = 0.080 against a >= 0.90 gate (FAIL, gating); E3 = 26/26 against >= 23 (PASS); E1_min and E1_mean both 1.0 (PASS). Lint, unit, security, and image all passed; release was skipped (main-only). The PR was blocked from merging by the branch protection on main and was closed unmerged. The change passed every unit test and every other check, and only the retrieval gate caught it — chunking regressions are now stopped at review time by measurement, not discovered after deployment.

## Release verification

Every push to `main` runs the nine-check release smoke against the release image, managed Postgres (Neon free plan, pgvector) and the real LLM provider, under a 512 MB container limit. The latest green run is https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41809139449 (commit `c149900`, 9/9). Conditions: GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt. Numbers: readiness 1.102 s, first query 1.98 s, warm query 0.556 s, peak memory 230.8 MiB.

The nine checks: image revision label equals the commit; `/healthz` 200 and commit matches; `/readyz` database and embedder ok; landing page 200 HTML with CSP; demo documents listed; sample question answered with a citation; nonsense question refused; anonymous upload 403; rapid queries hit the per-IP cap.

What this baseline does not prove:

- public reachability — there is no persistent host; the smoke runs in CI;
- how a free host behaves when idle — no idle period is exercised;
- long-running stability — the run is minutes, not days;
- behavior under real user traffic — the checks are sequential, not a load test.

## Service-level evaluation (M8)

Method. `evaluation/run_service_eval.py` runs the shipped image
(`docmind-service:m8`, 512 MB limit) against a fresh local database, creates
a throwaway API key, uploads the evaluation paper through the real API
(49 chunks), and asks the 16 evaluation questions (d01–d12, a01–a04; the
web questions w01–w04 are out of scope) through `POST /v1/query` with the
semantic cache disabled. Runs A and B use the shipped configuration
(evidence threshold 0.35, citations required, guardrails on). Run C is the
ablation: the same run with `DOCMIND_GUARDRAILS_ENABLED=false`, which
restores the M3-era prompt and removes the evidence gate and the validators.
An answer counts as an abstention when the service refuses it or the text
matches the Project 6 abstention patterns (`evaluation/scoring.py`,
unimproved); the rule and its 20 pinned examples are recorded in
`DECISIONS.md` and `tests/test_abstention.py`.

Incident. Run A crossed a cluster of transient provider failures: five
questions (d08, d10, d11, d12, a03) returned HTTP 503 with zero provider
calls spent. Following the failure rule, only those five were re-run
(5 further requests): four resolved, and d08 returned 503 again on a second
and a third attempt while neighbouring questions succeeded. Run A below is
the merged record (original + repair); d08 stands as a provider-availability
casualty, with its facts answered 2/2 by run B. The variance rule requires
stating any A–B difference beyond 2 facts: the original runs differ by 9 S1
facts, the repaired A and B by 6 — provider nondeterminism across identical
requests is larger than the 2-fact band, and the 503 cluster explains part
of run A's original gap.

| Gate | Threshold | Run A | Run B | Run C (ablation) |
|---|---|---|---|---|
| S1 key facts | ≥ 22 / 26 | 10 / 26 | 16 / 26 | see below |
| S2 abstentions | ≥ 3 / 4 | 4 / 4 | 4 / 4 | see below |
| S3a valid citations | ≥ 0.95 | 1.000 | 1.000 | n/a — no citation requirement in the ablated configuration |
| S3b answers with citation | ≥ 0.90 | 0.875 | 1.000 | n/a |
| S4 citation supports fact | ≥ 0.75 target | 0.667 | 0.875 | n/a |
| S5 mean prompt tokens | ≤ 3200 | 2002 | 2351 | see below |

S1 fails its pre-registered gate in both guardrails-on runs. The threshold
was not re-registered; the failure and its measured causes are the result.

Why S1 falls short — the decomposition, measured offline against the eval
database (no provider calls). Run B loses 10 facts: d03 −2, d07 −3, d09 −2,
d11 −2, d12 −1.

- **The evidence gate (5 facts).** For d07, all three fact-bearing chunks
  score below the 0.35 evidence threshold (best 0.3367); for d09 both facts
  sit in one chunk scoring 0.2209. Those facts were in the retrieved top-10
  (they count toward E3) but never entered the prompt. The 0.35 threshold
  was calibrated on answerable top-1 scores (minimum 0.3737); facts living
  in lower-ranked chunks score lower and fall through the gate.
- **The grounding validator (4 facts).** d03 and d11 were refused
  `ungrounded` in both runs although their fact chunks were in the prompt
  at 0.4521 and 0.6808. The validator is all-or-nothing: one unsupported
  claim in a draft discards the whole answer after one retry. On a famous
  paper the model drafts from memory as well as from context, which is the
  likely trigger; the refused drafts are not returned by the API, so this
  mechanism is inferred from the refusal reasons, not observed per claim.
- **Partial answers (1 fact).** d12 answered with 1 of its 2 facts.

Lowering the evaluation threshold to 0.30 would recover at most d07's
3 facts; d09's chunk at 0.22 is out of reach of any threshold that still
refuses the absent questions. The refinements this points to — fact-aware
gating and per-claim grounding instead of all-or-nothing refusal — are
Project 9 work, recorded in `DECISIONS.md`.

### Project 6 vs Project 7 on the same questions

| | P6 baseline (single) | P6 single call | P6 multi-agent | P7 run A | P7 run B |
|---|---|---|---|---|---|
| S1 key facts | 22 / 26 | 23 / 26 | 22 / 26 | 10 / 26 | 16 / 26 |
| S2 abstentions | 4 / 4 | 4 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |
| S3 answers with citation | n/a — citations not requested | n/a | n/a | 0.875 | 1.000 |
| Mean prompt tokens | 2549 | 2559 | 5856 | 2002 | 2351 |

Why this comparison is not apples-to-apples:

- P7 runs a new prompt that demands citations; P6's prompt did not.
- P7's stack (pgvector retrieval, ONNX embeddings inside the service,
  evidence gating, grounding validation) differs from P6's in-process
  pipeline; the retrieval layer alone scores 23 / 26 (E3).
- The web questions are excluded from P7's service evaluation.
- The corpus is a famous paper: the evaluating model may know it from
  memory in both projects, which inflates raw answering and, in P7,
  also triggers grounding refusals.

## Retrieval recall curve

Definition, frozen: key-fact recall on d01–d12 is the share of the 26 key
facts present in the top-10 retrieved context, under each project's own
tuned settings.

| Stage | Recall | Conditions |
|---|---|---|
| Project 6, initial | 16 / 26 = 61.5% | 800-word chunks, top-k 4 |
| Project 6, tuned | 24 / 26 = 92.3% | 150-word chunks, 25-word overlap, top-10 |
| Project 7 | 23 / 26 † = 88.5% | pgvector top-10, 150/25 chunks, ONNX MiniLM (the E3 measurement) |
| Project 5 | to be measured | the common-set comparison runs in Project 9 |
| Project 9 | to be measured | held-out set: `evaluation/heldout/manifest.json` |

The Project 7 point sits one fact below Project 6's tuned point for the
reason recorded with the E3 post-hoc change (a pypdf version difference
moved one fact across a chunk boundary); the retrieval ranking itself is at
parity (E2 = 1.000). Nothing in this curve is estimated: the two
"to be measured" rows stay empty until Project 9 runs them.
