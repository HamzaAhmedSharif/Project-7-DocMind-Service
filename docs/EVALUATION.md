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

Every push to `main` runs the nine-check release smoke against the release image, managed Postgres (Neon free plan, pgvector) and the real LLM provider, under a 512 MB container limit. The latest green run is https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/42343057863 (commit `617f16d`, 9/9). Conditions: GitHub-hosted runner, 512 MB container limit, Neon free plan, Frankfurt.

The nine checks: image revision label equals the commit; `/healthz` 200 and commit matches; `/readyz` database and embedder ok; landing page 200 HTML with CSP; demo documents listed; sample question answered with a citation; nonsense question refused; anonymous upload 403; rapid queries hit the per-IP cap.

What this baseline does not prove:

- public reachability of the API — the smoke runs in CI; the public demo added 2026-11-07 exposes a UI front end only, no API;
- how a free host behaves when idle — no idle period is exercised;
- long-running stability — the run is minutes, not days;
- behavior under real user traffic — the checks are sequential, not a load test.

## Public demo (2026-11-07)

After M8 closed, on the owner's instruction, a public UI demo was added
on a free Hugging Face Gradio Space (ZeroGPU), following the Project 6
pattern: the service package at `79c596a` is copied unchanged, a Gradio
front end calls the FastAPI app in-process (anonymous, public tenant,
demo configuration), and the Space's secrets are the production Neon
strings plus a dedicated Groq key (`hf-demo`). Docker Spaces are
paywalled behind Hugging Face PRO, and the M5 host evaluation's
reservations about the Gradio route (not the gated image; a
GPU-decorated function on a CPU workload; the last free slot) are
recorded in `DECISIONS.md` and stand as disclosed trade-offs. Live
verification on 2026-11-07, anonymous through the Space's Gradio API:
the demo question d01 answered with citations (pp. 24-25,
semantic-cache hit); a novel on-corpus question about the MAP function
answered with a live generation (1 LLM call, 388 prompt tokens,
citation p. 30); an off-corpus question refused with `low_evidence`.
The demo changes no M8 measurement; S1 stands as recorded.

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

Run C crossed the same failure mode twice over: twelve questions returned
503 in the original run and five of them again in the first repair.
Following the failure rule, the affected questions were re-run twice
(5 + 3 further requests). d10 and d11 returned 503 on all three attempts
each, and the absent questions a02 and a03 could not be measured either;
they stand as provider-availability casualties. Run C's S1 is therefore a
lower bound, and its recorded S2 of 2 / 4 counts a02 and a03 as
non-abstentions although neither was ever successfully asked.

| Gate | Threshold | Run A | Run B | Run C (ablation) |
|---|---|---|---|---|
| S1 key facts | ≥ 22 / 26 | 10 / 26 | 16 / 26 | 19 / 26 (lower bound) |
| S2 abstentions | ≥ 3 / 4 | 4 / 4 | 4 / 4 | 2 / 4 (two unmeasurable) |
| S3a valid citations | ≥ 0.95 | 1.000 | 1.000 | 1.000 |
| S3b answers with citation | ≥ 0.90 | 0.875 | 1.000 | 0.625 |
| S4 citation supports fact | ≥ 0.75 target | 0.667 | 0.875 | 0.700 |
| S5 mean prompt tokens | ≤ 3200 | 2002 | 2351 | 1741 |

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

What the ablation prices. Run C — the same retrieval and model with the
guardrails off — scores at least 19 / 26 on S1 (a lower bound; d10 and
d11 unmeasurable), above both guardrails-on runs (A 10, B 16). The
validator refusal disappears where it can be measured (d03 scores 2 / 2
in run C, refused in both guardrails-on runs), and the gate-funnel
questions partly recover (d07 2 / 3 against 0 / 3 in run B; d09 1 / 2
against 0 / 2). The guardrail stack's measured price on this set is at
least 3 facts against the better guardrails-on run. What the price buys
is the injection resistance measured at M6 (0 / 15 with guardrails on,
7 / 15 off) and citation discipline: with no citation requirement, only
0.625 of run C's answers carry a citation (S3b), against 1.000 in run B.
Abstention did not degrade on the two absent questions that could be
measured in run C — the model declines from an empty context in both
configurations. Mean prompt tokens fall to 1741 in run C because the
validator's retry loop never runs.

## S1 remediation (P7.1) — after remediation (post-hoc iteration, tuned on the evaluation questions)

M8 closed with S1 failing its gate in both guardrails-on runs, and the
decomposition pointed at two mechanisms inside the service stack: the
evidence gate and the all-or-nothing grounding validator. P7.1 changed
the code on the strength of that decomposition, not the gate: the
evidence gate was conformed to the M6.4 spec (a top-1 test only — the
shipped code had filtered chunks one by one, dropping fact-bearing
chunks below the threshold from the prompt), and a citation-repair
retry was added (one retry, on an `ungrounded` outcome only, with an
explicit cite-the-chunks instruction). Usage accounting after a retry
now merges both calls. Prompt v2, sanitization, thresholds and the
gates are unchanged; the runs below are labelled exactly as they are —
after remediation (post-hoc iteration, tuned on the evaluation
questions). Tuned on the same 12 questions; held-out check is
Project 9.

Method. Runs A2 (2026-11-07) and B2 (2026-11-08) use image
`docmind-service:p71` (commits `1925429`, `c49699b`) and the same
configuration, corpus, questions and failure rule as M8's runs A and
B. Both crossed the provider 503 wall: A2 needed five repair rounds
(a03, a04 never answered), B2 three (d10, a01–a04 never answered).
R1 was re-run last, on arm only, 1 repeat (see `DECISIONS.md` for why
the second repeat was dropped).

| Gate | Threshold | Run A (M8) | Run B (M8) | Run A2 | Run B2 |
|---|---|---|---|---|---|
| S1 key facts | ≥ 22 / 26 | 10 / 26 | 16 / 26 | 22 / 26 | 17 / 26 |
| S2 abstentions | ≥ 3 / 4 | 4 / 4 | 4 / 4 | 2 / 4 (a03, a04 unmeasurable) | 0 / 4 (all four unmeasurable) |
| S3a valid citations | ≥ 0.95 | 1.000 | 1.000 | 1.000 | 1.000 |
| S3b answers with citation | ≥ 0.90 | 0.875 | 1.000 | 0.846 | 0.643 |
| S4 citation supports fact | ≥ 0.75 target | 0.667 | 0.875 | 0.909 | 0.889 |
| S5 mean prompt tokens | ≤ 3200 | 2002 | 2351 | 2083 | 1572 |

Per-question, A2 vs B2 (facts found / total): d01 2/2, 2/2; d02 2/3,
3/3; d03 2/2, 1/2; d04 2/2, 2/2; d05 2/2, 2/2; d06 2/2, 2/2; d07 3/3,
2/3; d08 2/2, 2/2; d09 refused `ungrounded` 0/2 in both runs, even
after the repair retry; d10 2/2, unmeasured (503 on every attempt);
d11 2/2, refused `ungrounded` 0/2 even after the repair retry; d12
1/2, 1/2. The three M8 losses the remediation targeted — d07 (gate
funnel), d03 and d11 (validator refusals) — all recovered in A2
(3/3, 2/2, 2/2) but only partly in B2 (2/3, 1/2, refused). d09 still
refuses in both runs: the repair retry cannot help where the draft
itself carries no valid citation. d02 and d12 stay partial in both
runs.

What the two runs say together. A2 met the S1 gate (22/26) and B2 did
not (17/26) on identical code, so the remediation's measured effect is
smaller than run-to-run provider nondeterminism on this set (the A2–B2
gap is 5 facts; the M8 A–B gap after repair was 6). Neither run alone
proves a stable pass or a stable fail; the honest reading is that the
gate conformance and the repair retry recovered the three targeted
losses in one run and not the other. S2 cannot be compared across the
two runs: A2 measured two abstentions and left two questions
unmeasured, B2 measured none. R1 re-confirmation (on arm, 1 repeat):
0/15 attacks succeeded, model resisted 15/15 — the repair retry did
not weaken injection resistance. Provider spend for P7.1: 42 recorded
requests (A2 14, B2 13, R1 15) against the 100 cap; A2's 14 is a lower
bound under the pre-fix accounting (see `DECISIONS.md`).

## S1 remediation 2 (P7.2) — after remediation (post-hoc iteration, tuned on the evaluation questions)

P7.2 tested whether the losses P7.1 left behind were still service
losses. A free diagnostic (zero provider calls) came first: of the 26
key facts, 23 are present in the retrieved top-10 context — the
groundable ceiling C = 23, recomputed with the frozen scorer and
matching E3. The three retrieval-absent facts are d02's softmax and
scaling facts (their bearing chunk ranks 11th for d02) and d09's
label smoothing (its only bearing chunk ranks 18th). Two changes
were pre-registered in `DECISIONS.md` before any run: the
citation-repair retry became quote-anchored (the retry must first
quote the chunk lines it relies on, verbatim, with their ids, then
answer citing the same ids), and the prompt moved to p7-v3, adding a
completeness instruction while keeping the RULES hardening text
byte-identical. Retrieval, thresholds, the scorer and the questions
are unchanged. Success was pre-registered as S1 ≥ 22/26 in BOTH
runs, reported raw and as "k of C reachable". Tuned on the same 12
questions; held-out check is Project 9.

Method. Runs A3 (2026-11-09) and B3 (2026-11-10) use image
`docmind-service:p72` (commit `806954b`) and the same configuration,
corpus and questions as A2/B2. Both first passes crossed the
provider 503 wall (A3 measured 5 of 16 questions, B3 3 of 16) and
took all five repair rounds; a03 and a04 were never measured in
either run. R1 was re-checked last, on arm only, 1 repeat, because
the prompt changed.

| Gate | Threshold | Run A3 | Run B3 |
|---|---|---|---|
| S1 key facts | ≥ 22 / 26 in both runs | 20 / 26 (19 of 23 groundable) | 21 / 26 (19 of 23 groundable) |
| S2 abstentions | ≥ 3 / 4 | 2 / 4 (a03, a04 unmeasurable) | 2 / 4 (a03, a04 unmeasurable) |
| S3a valid citations | ≥ 0.95 | 1.000 | 1.000 |
| S3b answers with citation | ≥ 0.90 | 0.857 | 0.857 |
| S4 citation supports fact | ≥ 0.75 target | 0.818 | 0.909 |
| S5 mean prompt tokens | ≤ 3200 | 2388.5 | 2171.5 |

Per-question, A3 vs B3 (facts found / total): d01 2/2, 2/2; d02 2/3,
3/3; d03 1/2, 1/2; d04 2/2, 2/2; d05 2/2, 2/2; d06 2/2, 2/2; d07 2/3,
2/3; d08 2/2, 2/2; d09 0/2, 0/2 — answered in both runs (A3 via the
repair retry, B3 on the first pass) with a verbatim quote of the
regularization passage and an explicit statement that the excerpts
do not enumerate the techniques; d10 2/2, 2/2; d11 2/2, 2/2; d12
1/2, 1/2. No document question was refused in either run.

What the two runs say together. The pre-registered gate is not met
(20 and 21 against ≥ 22 in both), and the honest frame is the
groundable one: both runs found exactly 19 of the 23 facts present
in their context. The single raw difference is d02's softmax fact —
missed in A3 on a hyphenated "soft-max" the frozen scorer regex
cannot match, scored in B3 from partial evidence (the
model-memory confound the diagnostic proved on this question). The
four groundable losses are identical in both runs and none of them
is a service-stack refusal: d09's residual-dropout fact is a
retrieval-rank loss (the enumeration chunk ranks 18th); d03 and d12
are scorer-phrasing losses (the answers state the content in words
the frozen regexes do not match); d07's sinusoid fact is a genuine
omission the completeness instruction did not recover. Where
A2–B2 differed by 5 facts on identical code, A3–B3 differ by 1 —
the remaining losses are systematic, and the lever that addresses
the largest of them (retrieval rank) is Project 9's variable, not
another P7 iteration. S2 held under the stronger repair: a01 and
a02 abstained in both runs, each after the repair retry fired.
R1 re-check (on arm, 1 repeat): 0/15 attacks succeeded, model
resisted 15/15 — the p7-v3 prompt did not weaken injection
resistance. Provider spend for P7.2: 48 recorded requests (A3 17,
B3 16, R1 15) against the 70 cap.

## S1 retrieval unfrozen (P7.3) — after remediation (post-hoc iteration, tuned on the evaluation questions)

P7.2 closed with the gate unmet and the largest remaining loss
identified as retrieval rank — the lever P7.2 had deliberately
frozen as Project 9's variable. The owner then decided, against the
manager's leave-as-is recommendation, to spend that lever inside
Project 7: P7.3 unfreezes retrieval with one real service change, a
local zero-cost cross-encoder reranker, under a final stop rule (a
miss closes Project 7 permanently, no P7.4) and a pre-registered
gate of S1 ≥ 22/26 in BOTH runs. Project 9 must be redesigned
around the spent variable (see `docs/P9-REDESIGN-BRIEF.md`).

Design. The dense stage (ONNX `all-MiniLM-L6-v2`, exact cosine,
same 150/25 chunker) returns 25 candidates; a local ONNX
cross-encoder (`Xenova/ms-marco-MiniLM-L-6-v2`, int8 quantized)
reranks them against the question; the top 10 go into the p7-v3
prompt unchanged. The evidence gate stays a dense top-1 test
(0.35) and chunk scores stay the dense cosine, so the citation
contract is unchanged. Admissibility was computed free before any
provider run: the harness reproduced the P7.2 baseline (C = 23,
ranks 11/11/18), the reranker puts chunk 11 into d02's context
(position 4) and chunk 27 into d09's (position 4 full-batch,
position 5 under the shipped 5-pair sub-batches) with no
baseline-present fact lost, so the new ceiling is C′ = 26; the
projected mean prompt tokens are 2544 against a 3000 admissibility
bar; memory peaks at 324.2 MB under concurrency 10 in a 512 MB
container (the fit needed sub-batching, the ORT arena off, an
inference lock and glibc malloc tuning — the arena alone grows past
1.3 GB); rerank p95 is 339 ms in the foreground. Sub-batching
changes the int8 model's scores (dynamic activation quantization),
so admissibility was re-verified under the shipped scoring.
Frozen throughout: questions, scorer regexes, evidence threshold,
cache τ 0.86, prompt p7-v3, embedding model, chunker, corpus,
held-out manifest. Tuned on the same 12 questions; held-out check
is Project 9.

Method. Runs A4 (2026-11-13) and B4 (2026-11-14) use image
`docmind-service:p73` (commits `9178775`–`21a1e3a`) and the same
configuration, corpus and questions as A3/B3. A4's first pass and
one repair round hit a total provider 503 wall (0 spent); a runtime
restart then killed a repair round mid-run, losing 8 calls' results
before the merge (no ledger rows — rows are written at merge); 3
further rounds completed the run. B4's first pass hit 8 questions
at 503 and took 3 repair rounds. R1 was re-checked last, on arm
only, 1 repeat.

| Gate | Threshold | Run A4 | Run B4 |
|---|---|---|---|
| S1 key facts | ≥ 22 / 26 in both runs | 23 / 26 (23 of 26 groundable) | 24 / 26 (24 of 26 groundable) |
| S2 abstentions | ≥ 3 / 4 | 4 / 4 | 4 / 4 |
| S3a valid citations | ≥ 0.95 | 1.000 | 1.000 |
| S3b answers with citation | ≥ 0.90 | 1.000 | 1.000 |
| S4 citation supports fact | ≥ 0.75 target | 1.000 | 1.000 |
| S5 mean prompt tokens | ≤ 3200 | 2782.8 | 2782.8 |

Per-question, A4 vs B4 (facts found / total): d01 2/2, 2/2; d02 3/3,
3/3; d03 1/2, 1/2; d04 2/2, 2/2; d05 2/2, 2/2; d06 2/2, 2/2; d07 2/3,
3/3; d08 2/2, 2/2; d09 2/2, 2/2 — both previously-absent facts
recovered in both runs; d10 2/2, 2/2; d11 2/2, 2/2; d12 1/2, 1/2.
No document question was refused in either run. a01 and a02
abstained by refusal in both runs; a04 abstained by refusal in
both runs; a03 abstained in prose in both runs (no formal refusal,
answer text matches the abstention pattern).

What the two runs say together. The pre-registered gate is met in
both runs (23 and 24 against ≥ 22), and the reranker did exactly
the work the design check predicted: d02 and d09 — the two
questions whose facts the dense top-10 could not reach — score
full marks in both runs, and nothing the dense stage grounded was
lost. The remaining losses are the ones the design check flagged
as at-risk and not design targets: d03 and d12 are scorer-phrasing
losses (the answers state the content in words the frozen regexes
do not match), and d07's sinusoid fact is a genuine omission that
B4 recovered and A4 did not — the only run-to-run difference, and
the honest size of provider nondeterminism on this set once the
systematic losses are addressed. S2 held at 4/4 in both runs with
no safety regression: the absent questions that abstained in A3/B3
abstained again. R1 re-check (on arm, 1 repeat): 0/15 attacks
succeeded, model resisted 15/15 — the reranker did not weaken
injection resistance (the harness bypasses retrieval by design).
Provider spend for P7.3: 62 recorded requests (A4 21, B4 26, R1
15) against the 80 cap, plus 1 release-smoke on the implementation
push. Project 7 closes here: the reranker ships on
(`RERANKER_ENABLED` default true), and there is no P7.4.

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
| Project 7, P7.3 | 26 / 26 = 100% | dense top-25 reranked to top-10 by the ONNX cross-encoder (E3 on the final context; the dense stage alone still measures 23 / 26) |
| Project 5 | to be measured | the common-set comparison runs in Project 9 |
| Project 9 | to be measured | held-out set: `evaluation/heldout/manifest.json` |

The Project 7 point sits one fact below Project 6's tuned point for the
reason recorded with the E3 post-hoc change (a pypdf version difference
moved one fact across a chunk boundary); the retrieval ranking itself is at
parity (E2 = 1.000). Nothing in this curve is estimated: the two
"to be measured" rows stay empty until Project 9 runs them.
