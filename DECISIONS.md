# DocMind Service - Decisions & Engineering Notes

Decisions are logged as they are made, with the evidence available at the time. Rejected alternatives are listed because they are part of the decision.

## Decisions

### Decision: Project 7 builds a service on top of DocMind instead of a new RAG system
- Context: Project 6 measured three pipelines on 20 questions. Answer quality was a tie within noise (22, 23 and 22 of 26 key facts, strict), the multi-agent version used about 2.3 times the prompt tokens of the single call on document questions, and retrieval, not orchestration, caused the one real failure (see Project 6 `evaluation/RESULTS.md`).
- Chosen: spend Project 7 on what a measured RAG system lacks to be used: an API contract, storage, tests and CI gates, deployment, security and observability. The default query mode will be a single call; multi-agent stays an opt-in mode.
- Rejected: adding more agents or features to the pipeline (no measured benefit); hybrid search and a reranker here (they are the Project 9 stage on the shared evaluation curve; Project 7 stays hybrid-ready with a keyword column and a retriever interface).
- Tradeoff accepted: the service reuses a pipeline whose evaluation document is famous, so answer quality cannot be separated from model memory until Project 9 adds a held-out document.
- Would revisit if: the service-level evaluation (M8) contradicts the Project 6 findings.

### Decision: hosting path B, Render free web service plus Neon free Postgres
- Context: the budget is zero and no payment card is available. Free-tier options were checked on 2026-10-27. Hugging Face documents that Docker Spaces on the free CPU tier need a subscription; Google Cloud Run needs a billing account; Koyeb needs a card for verification; Fly.io has no free tier for new accounts; Oracle Always Free needs a card and has capacity limits. Render's free web service needs no card (512 MB RAM, spins down after 15 minutes idle) and Neon's free plan needs no card (0.5 GB per project, 100 compute-hours a month, scale to zero after 5 minutes, pgvector supported).
- Chosen: Render free plus Neon free, with a slim image (ONNX embeddings instead of PyTorch) to fit 512 MB. Render's current terms are checked at signup because a plan change on 1 August 2026 was reported.
- Rejected: Hugging Face Docker Space (paid); Cloud Run (card); Koyeb and Fly.io (card); Oracle Always Free (card, capacity).
- Tradeoff accepted: cold starts (idle spin-down and database scale-to-zero) and a hard 512 MB memory budget.
- Would revisit if: Render's terms no longer fit. The fallback is to publish the image to GHCR and have CI deploy an ephemeral stack and run the smoke test; that would be described as verified in CI, not hosted.

### Decision: a dedicated Python 3.12 environment instead of the shared `rag` environment
- Context: in Project 6, installing the pinned requirements into the shared `rag` environment downgraded numpy 2.2.6 to 1.26.4, transformers 5.16.1 to 4.57.6, langchain 1.3.18 to 0.3.7, langgraph 1.2.11 to 0.2.39, streamlit 1.63.0 to 1.39.0 and faiss-cpu 1.15.0 to 1.9.0, and pip reported dependency conflicts (see Project 6 `DECISIONS.md`).
- Chosen: a new conda environment at `B:\Applications\MiniConda\envs\docmind-service` with Python 3.12, and pinned `requirements.txt` and `requirements-dev.txt` written from the versions installed at M1.
- Rejected: reusing `rag`.
- Tradeoff accepted: one more environment to maintain and extra disk space.
- Would revisit if: disk space becomes a problem.

### Decision: contract first
- Context: the service has to be usable by clients and testable before its behavior exists.
- Chosen: Pydantic schemas and stub routes that return `501` problem details define the API; `openapi.json` is committed and a test fails if the app drifts from it; every error uses `application/problem+json`. API keys are declared in the contract now and enforced from M6. Evidence: `tests/test_contract.py` and `openapi.json` in the M1 commit.
- Rejected: generating the contract only at the end (changes would not be visible in review).
- Tradeoff accepted: extra churn when a schema changes, since `openapi.json` must be regenerated in the same commit.
- Would revisit if: the contract file creates more friction than review value.

## Engineering Notes

Notes are recorded in the milestone sections below.

## M2 - service core on fakes (2026-10-30)

### Decision: ports and in-memory fakes for the service core
- Context: M2 has to be testable without a database, an embedding model or a language-model provider, none of which a reviewer or a CI runner has by default.
- Chosen: two small interfaces (`Retriever`, `LLMClient`) in `docmind_service/domain.py`, a deterministic in-memory retriever and a fake model in `docmind_service/fakes.py` (also the default demo mode), and a pure `answer_question` function in `docmind_service/query.py` with no web-framework imports. Evidence: 43 tests pass offline in seconds.
- Rejected: patching network calls inside tests; calling a live provider from CI (needs secrets and spends the token budget).
- Tradeoff accepted: a fake can drift from the real adapter; the real adapters implement the same interfaces, and M3 adds a retrieval parity test against the Project 6 evidence.
- Would revisit if: an adapter needs behavior the interfaces cannot express.

### Decision: refuse without calling the model when retrieval returns nothing
- Context: tokens are the scarce resource; Project 6 measured about 2,550 prompt tokens for a single call under an 8,000 tokens per minute limit.
- Chosen: an empty retrieval returns `refused: true` with reason `no_evidence`, zero calls and a fixed answer. Evidence: `test_query_refuses_without_calling_the_llm_when_nothing_matches` in `tests/test_query_api.py`.
- Rejected: always calling the model and letting it say it does not know.
- Tradeoff accepted: this only catches empty retrieval; a score threshold for weak retrieval belongs to the guardrails in M6.
- Would revisit if: the M6 threshold makes this rule redundant.

### Decision: request ids and JSON logs that never contain question or answer text
- Context: the service will log queries for later evaluation work, and a public demo must not store user text unredacted.
- Chosen: every response carries `X-Request-ID` (an incoming id is kept only if it matches a safe pattern, otherwise a new one is generated); logs are JSON lines with the request id, status, duration, token counts and chunk counts, never the question or the answer; error bodies include the request id. Evidence: `tests/test_observability.py` checks that a unique question string and a unique answer string never appear in any log line of a successful query, and that an exception message containing the question never appears in the logs of a failed request (see the note below). The query log also records `prompt_version`, so later evaluation runs can be tied to the exact prompt.
- Rejected: logging full requests for easier debugging.
- Tradeoff accepted: debugging relies on ids and counts; a redacted query log for evaluation work arrives in M6.
- Would revisit if: M6's redaction passes review and a redacted text log is needed.

### Decision: bound the document filter at 1 to 100 ids
- Context: the query request accepted an unbounded list of document ids; M3 turns it into a database filter, so an oversized list is a cheap way to make requests slow.
- Chosen: `document_ids` is either omitted (all documents) or has 1 to 100 entries; anything else is a 422, and an empty list is rejected because it is almost certainly a client mistake. The contract change is the `minItems` and `maxItems` pair on `QueryIn.document_ids` in `openapi.json`. Evidence: `test_document_ids_must_have_between_1_and_100_entries` checks 0, 100 and 101 entries.
- Rejected: leaving the list unbounded until the database exists; silently truncating it.
- Tradeoff accepted: a client with more than 100 documents must omit the filter or query in groups.
- Would revisit if: real usage needs larger filters.

### Note: exception messages leaked into logs through two paths
- Symptom: a pre-commit review reproduced a 500 whose ERROR log line contained the question, because a retriever raised an exception whose message included it. A real server has a second path: Starlette re-raises after its error handler and uvicorn logs the full traceback, message included, through its own logger.
- Cause: the last line of a Python traceback is the exception message, and both the JSON formatter and uvicorn's default formatter printed it. The first redaction test only covered a successful query.
- Fix: the JSON formatter now writes only the exception type and the stack frames; a filter on the `uvicorn.error` logger does the same for uvicorn's records; the `docmind` logger no longer propagates to the root logger. Evidence: three unit tests, and a real-server check in which a retriever that raised with the question in its message left 2 occurrences of the question in the server logs before the fix and 0 after.
- Tradeoff accepted: debugging an unexpected error relies on the exception type and the stack frames, not the message.
- Lesson: test the failure path of a redaction claim with a unique string; a test that only covers success proves nothing about the paths that fail.

### Note: Starlette deprecates httpx in its test client
- Symptom: pytest warned that using httpx with the Starlette test client is deprecated and to install httpx2.
- Cause: the test client is moving to a different HTTP library.
- Fix: `requirements-dev.txt` now pins httpx2 2.16.0 in place of httpx; the full suite passes with only httpx2 installed and the warning is gone.
- Lesson: read the warnings of a green run; the next dependency upgrade would have turned this one into a failure.

## P0 - CI carry-over chores (2026-11-03)

### Decision: run the pinned actionlint binary directly when Docker is unavailable
- Context: P0.5 step 3 calls `docker run --rm -v "${PWD}:/repo" -w /repo rhysd/actionlint:1.7.7`, but `docker info` fails because the Docker Desktop daemon is not running. Starting it requires Hamza ([H2]), and the rest of P0 can continue.
- Chosen: download the official actionlint 1.7.7 Windows amd64 release, confirm its SHA-256 against the published checksums file, and run it directly on `.github/workflows/ci.yml`. Evidence: computed SHA-256 `7f12f1801bca3d480d67aaf7774f4c2a6359a3ca8eebe382c95c10c9704aa731` matched the checksums line; actionlint printed no findings and exited 0 on 2026-11-03.
- Rejected: skipping the workflow lint; using an unpinned `latest` tag; waiting for Docker and blocking independent P0 steps.
- Tradeoff accepted: the check ran as a local pinned binary instead of inside the container; the workflow file and actionlint version are the same.
- Would revisit if: Docker Desktop is started; rerun the container command for an exact match.

### Note: gitleaks-action fails on a root-commit push
- Symptom: the first CI run on `main` passed lint and test but failed the secrets job at `Run gitleaks/gitleaks-action@v2`; no leak was reported.
- Cause: `gitleaks-action` computes the range `<oldest>^..<newest>` from the push event. For a push whose range starts at the root commit, that parent does not exist; git fails with an unknown revision, gitleaks scans nothing, and exits 1.
- Fix: replaced the action with the pinned gitleaks 8.24.3 Linux binary downloaded from the release page, verified with the published SHA-256 `9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c`, then run as `gitleaks git --no-banner --redact --verbose .` over the full checkout. Evidence: checksum matched; actionlint 1.7.7 found no workflow errors. CI result is pending Hamza's push ([H1]).
- Lesson: a check that fails for its own reasons erodes trust in the green one.

## M3 - Document storage, retrieval, and evaluation pre-registration (2026-11-03)

### Decision: global word-stream chunking with first-word page attribution and parity with P6
- Context: M3.3 needs a chunker that matches Project 6's `chunk_text(text, chunk_size, overlap)` so retrieval evaluation can compare P7 against P6 references.
- Chosen: `docmind_service/chunking.py` with `chunk_pages(pages, words=150, overlap=25)` that normalizes whitespace, joins pages into a word stream, attributes each chunk to the page of its first word, and passes a P6 parity test (`tests/test_chunking.py::test_matches_p6_chunk_text_on_the_same_word_stream`, skips when P6 is absent). Evidence: 401-word stream matches P6 exactly; `CHUNK_WORDS=150`, `CHUNK_OVERLAP=25` per the script.
- Rejected: per-page chunking with independent windows (would not match P6's cross-page word stream); different chunk sizes (the script fixes 150/25).
- Tradeoff accepted: a chunk can span a page boundary; its `page` is the page of its first word, which is an approximation for multi-page chunks.
- Would revisit if: P6's chunker changes or M8 needs finer page attribution.

### Decision: exact cosine search, no ANN index, `tsv` column kept hybrid-ready
- Context: M3.5 needs vector search in PostgreSQL with pgvector. HNSW/ANN was considered but adds build time and approximation error.
- Chosen: `migrations/001_init.sql` creates `chunks.embedding vector(384)` with exact `<=>` cosine distance ordering and no index; `chunks.tsv` is a generated `tsvector` column for future hybrid search. Evidence: `tests/test_db.py` passes against `docmind_test`; `scripts/measure_rss.py` shows ~162 MB peak RSS.
- Rejected: HNSW index (`vector_cosine_ops`) — would speed up large corpora but add approximate results and build overhead; ORM (SQLAlchemy) — plain SQL with psycopg is simpler and matches the script's "plain-SQL migrations" requirement.
- Tradeoff accepted: exact search is O(n) per query; fine for the evaluation corpus (49 chunks) and expected scale; hybrid search deferred to a later milestone.
- Would revisit if: document counts grow beyond thousands.

### Decision: plain-SQL migrations, no ORM
- Context: M3.5 needs schema migration and a migration CLI.
- Chosen: `docmind_service/db.py` with `migrate()`, `make_pool()`, `load_dotenv()`, and a `python -m docmind_service.db migrate|status` CLI; `migrations/001_init.sql` is plain SQL with `CREATE EXTENSION IF NOT EXISTS vector`, `CREATE TABLE ...`, and indexes; an advisory lock (727001) serializes concurrent migrations; each missing version runs in its own transaction.
- Rejected: Alembic/SQLAlchemy migrations — adds a dependency and abstraction not requested; embedding migration SQL in Python strings — harder to review and version.
- Tradeoff accepted: SQL files are separate from code; the CLI needs `--env-file` support and reads `DOCMIND_DATABASE_URL_DIRECT` or `DOCMIND_DATABASE_URL`.
- Would revisit if: multi-branch migration conflicts become common.

### Decision: fastembed ONNX embedder with model files baked into the image and a unit-norm check
- Context: M3.4 needs sentence embeddings; PyTorch/sentence-transformers would exceed the 512 MB memory budget.
- Chosen: `docmind_service/embedding.py` with `OnnxEmbedder` wrapping `fastembed.TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")`, `dim=384`, unit-norm verification (corrects if needed), a 256-entry LRU query cache, and `warm_up()`/`clear_cache()`. `HashingEmbedder` is a deterministic dependency-free double for tests. Evidence: `tests/test_embedding.py` passes (unit HashingEmbedder without the model; model tests download and verify dim/norm/determinism).
- Rejected: sentence-transformers/PyTorch — too large for the 512 MB Render free tier; OpenAI embeddings — costs tokens and needs a key.
- Tradeoff accepted: the model downloads on first use (~6 min); the Dockerfile bakes it in at build time.
- Would revisit if: a different embedding model is required by M8 results.

### Decision: `tenant_id` from day one and the interface change
- Context: M3.2 adds `tenant_id` to `Retriever`, `DocumentStore`, `query.py`, and `main.py` while keeping `"public"` as the default for current single-tenant callers.
- Chosen: all retriever/store calls accept `tenant_id` (default `"public"`); `PgStore` filters `chunks.tenant_id`; upload/list/delete hardcode `tenant_id="public"`; `fakes.py` and tests updated for the new signature.
- Rejected: making `tenant_id` required everywhere (would break M2 callers); a separate multi-tenant middleware (over-engineering for single-tenant).
- Tradeoff accepted: existing single-tenant callers work unchanged; multi-tenant is ready when M6 adds auth.
- Would revisit if: M6's auth model requires tenant extraction from JWTs.

### Decision: the `_test` database guard
- Context: M3.8's retrieval evaluation ingests into `DOCMIND_TEST_DATABASE_URL`; an accidental run against the production `docmind` database would be destructive.
- Chosen: integration fixtures refuse a DSN whose database name does not end in `_test`; `fetch_corpus.py` and `run_retrieval.py` also validate the `_test` suffix.
- Rejected: relying on developer carelessness; a runtime confirmation prompt (not CI-friendly).
- Tradeoff accepted: the guard is in test code, not production; production code does not need it.
- Would revisit if: a staging database is added.

### Decision: provider throttling and shed policy
- Context: M3.7's `HostedLLM` must respect RPM/TPM limits and shed load instead of unbounded waiting.
- Chosen: `TokenBucket` at 90% of `HOSTED_RPM`/`HOSTED_TPM`; estimated tokens `len(prompt)//3 + 600`; if `wait > LLM_MAX_WAIT_SECONDS`, refund and raise `ProviderError(retry_after=ceil(wait))` (load shedding, no provider call); 429 retries at most twice with `min(delay, 20) + 0.5`; daily limits fail fast; 413 → `ProviderError("request too large")`; connection errors retry once after 1 s then fail with `retry_after=30`.
- Rejected: unbounded retries (could exhaust the token budget); retrying 413/401/403 (client errors, not transient).
- Tradeoff accepted: a shed request returns 503 to the caller; the token budget is preserved.
- Would revisit if: M8's load test shows shedding too aggressive.

### Note: reference fixtures contain vectors only (license)
- Symptom: the evaluation corpus PDF is under an arXiv non-exclusive license and must not be committed.
- Cause: `evaluation/fixtures/` contains `.npy` vector files and `.json` metadata only (~110 KB), no text and no PDF.
- Fix: `scripts/fetch_corpus.py` downloads the PDF by hash to `data/cache/` (git-ignored) at evaluation time; fixtures are derived from the P7-chunked text, not copied from the PDF.
- Evidence: `.gitignore` covers `data/`; `evaluation/fixtures/` holds only `.npy`/`.json`.
- Lesson: never commit licensed full-text; vectors are derivable and safe to commit.

### Note: corpus fetched by hash, never committed
- Symptom: `evaluation/corpus.json` pins arXiv `1706.03762v7` with SHA-256 `bdfaa68d...` (matches P6's copy exactly).
- Cause: the PDF is downloaded at evaluation time and verified against the manifest hash; `data/cache/` is git-ignored.
- Fix: `scripts/fetch_corpus.py` retries 3 times (2/5/10 s), verifies SHA-256, skips if cached and matches, exits non-zero on failure.
- Evidence: `data/cache/attention.pdf` exists locally but is not tracked by git.
- Lesson: hash verification prevents silent drift if arXiv replaces a versioned file.

### Note: gates pre-registered before results
- Symptom: `evaluation/gates.json` must exist before any evaluation runs.
- Cause: `evaluation/gates.json` was committed as a standalone `eval: pre-register gates` commit before `evaluation/results/retrieval-m3.json` was produced.
- Fix: `registered_on` is `2026-11-03`; `post_hoc_changes` is empty; the E3 post-hoc entry is in `DECISIONS.md` only.
- Evidence: `git log --format="%h %ad %s" --date=short -- evaluation/gates.json evaluation/results/retrieval-m3.json` shows gates before results.
- Lesson: pre-registration prevents threshold tuning after seeing results.
- Timeline correction (2026-11-03): the gates FILE existed and was frozen in the working tree before the evaluation ran, but its standalone commit `4374a00` was created after the run (HEAD during the run was `af79b1d`). See "Note: why evaluation/results/retrieval-m3.json stamps git_commit af79b1d".

### Post-hoc threshold change: E3
- Gate and original threshold: E3, `e3_key_facts_found >= 24` of 26 (gating).
- Measured value (source file, commit): 23/26 in `evaluation/results/retrieval-m3.json`.
- Fix attempts (three, each a different hypothesis, each with its result):
  1. Chunk count vs P6: 49 chunks, matches P6 exactly (PASS — not the cause). Manager FIX-1 extended this hypothesis with the extraction-TEXT comparison: 49 chunks and all checked `page` attributes agree, but every chunk's TEXT differs by pypdf-version whitespace — P6's own environment (rag env pypdf 5.0.1, byte-equal to P6's actually-stored `data/faiss_index_meta.pkl`) glues tokens ("divide each by√dk", "gradients4."), while P7's pypdf 6.21.4 separates them ("divide each by √dk", "gradients 4."). Boundary-sensitive at chunk 10/11: in the P6 text form "√dk" lands inside chunk 10 (IN d02's top-10); in the P7 text form the 150/25 boundary cuts the sentence at "divide each by" and leaves "√dk" in chunk 11 (OUT). Under the same measured ranking, verbatim P6 text would surface fact 3 (24/26); P7 text does not (23/26). Both d02 fact strings exist verbatim in P7's chunk text in scorer-matchable form (softmax in chunks 11, 12, 16, 17; √/square-root in 11, 12, 17, 25, 26), but every such chunk is outside d02's top-10 — chunks 11 and 12 are inside d03's top-10, which is why d03 scores full and d02 misses facts 2 and 3. Evidence and verbatim blocks: `reports/M3.md`, "Manager FIX-1" (2026-11-03). Gates.json, scorer and code untouched in that round; measured gates stay computed against P7's own chunks.json-text, which is also what the reference fixtures were built from, so the recorded 23/26 is internally consistent.
  2. E1 cosine vs reference vectors: 1.0 min / 1.0 mean (PASS — embedding parity confirmed).
  3. E2 top-10 overlap vs FAISS reference: 1.000 mean (PASS — retrieval matches P6 exactly).
- New threshold and the rule that sets it: threshold stays at 24/26; no change. The miss is inherent to the question set: the d02 softmax/scaling key facts and one d09 fact are not in the top-10 chunks retrieved by the same method P6 uses. Marked with † in `reports/M3.md`.
- Would revisit if: M8 changes the question set, chunking, or top-K.

### Post-hoc threshold change: E3 — completed
- Status: supersedes the "no change" entry above; that entry is left as written for the record.
- Decision: Hamza's Class C decision of 2026-11-03, communicated via the manager, completes the E3 post-hoc change. `evaluation/gates.json` now sets `E3.value = 23` (of 26) and records the change in `post_hoc_changes` (old_value 24, new_value 23, measured "23/26 in evaluation/results/retrieval-m3.json", date 2026-11-03).
- Measured value: 23/26, unchanged, in `evaluation/results/retrieval-m3.json`.
- The three attempts (full detail in the superseded entry): (1) chunk count vs P6: 49 = 49, PASS, with Manager FIX-1 proving the cause is extraction-text whitespace (pypdf 6.x token spacing vs P6's pypdf 5.0.1 shifted the d02 scaling sentence across the chunk 10/11 boundary); (2) E1 cosine 1.0 min / 1.0 mean, PASS; (3) E2 top-10 overlap 1.000, PASS.
- FIX-1 finding: both d02 fact strings exist verbatim in P7's chunk text in scorer-matchable form, but the chunks holding them are outside d02's top-10; the retrieved chunk 10 is cut at the 150/25 boundary exactly before "√dk". Retrieval parity (E2 = 1.000, E1 mean = 1.0) rules out a retrieval or embedding defect; the one-fact difference is the extraction-text boundary placement, not a lost fact.
- New threshold and the rule that sets it: `e3_key_facts_found >= 23` of 26 (gating). The measured 23/26 now passes; `evaluation/check_gates.py --stage retrieval` reports PASS. Dagger † appended to every E3 gate row/statement in `reports/M3.md`.
- Would revisit if: M8 changes the question set, chunking, pypdf version, or top-K.

### Note: why evaluation/results/retrieval-m3.json stamps git_commit af79b1d
- Symptom: the results file records `"git_commit": "af79b1dfeaa9add11693efe174ef090b8b6f4f88"`, a commit that predates every M3 commit.
- True sequence, exactly as it happened: (1) all M3 changes were present and uncommitted in the working tree while HEAD was still `af79b1d` (the P0 commit); (2) the retrieval evaluation ran in that state, and the script stamps the current HEAD, so the result records `af79b1d`; (3) only afterwards were the commits created: M3a `32b60cb`, M3b `576b7b9`, `eval: pre-register gates` `4374a00` (gates.json existed in the worktree, unchanged, before the run), M3c `1538e20` (which committed the results file), then FIX-1 `92f081c`.
- Cause: the stamp identifies the commit checked out at run time, not the content of the working tree; uncommitted changes are invisible to `git rev-parse HEAD`.
- Fix: none needed for the results (the working-tree content that ran is exactly what M3a–M3c commit); this note records the chronology. The earlier "gates pre-registered before results" note is corrected in the timeline respect: the gates FILE existed and was frozen before the run, while its standalone COMMIT came after the run.
- Lesson: when a run must be attributed to code, commit first and run from the commit; a dirty-tree stamp is only a lower bound.

### Note: gitleaks flags synthetic test values and the empty-placeholder artifact
- Symptom: the CI secrets job failed on commit `576b7b9` with four `generic-api-key` findings. Reproduced locally with the pinned gitleaks 8.24.3 (Linux tarball SHA-256 `9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c`, matching `.github/workflows/ci.yml`): `tests/test_config.py:28`, `tests/test_config.py:31`, `tests/test_llm.py:195`, and `.env.example:14`.
- Cause: the default `generic-api-key` rule flags high-entropy values assigned to key-like names. The tests use synthetic unique strings on purpose (they assert the value never leaks into exceptions, logs, or `repr`), and the `.env.example` finding is an artifact: the placeholder is empty, and the rule's whitespace class spans the newline and captures the NEXT line's variable name as the "secret" (the finding links `#L14-L15`). The P0 pre-commit regex targets real key prefixes only (`gsk_`, `tvly-`, `AIzaSy`, `AQ.Ab`, `ghp_`, `sk-`), so it does not catch synthetic unique strings or the artifact; only the pinned binary over full history does.
- Fix: `.gitleaksignore` (gitleaks' native fingerprints file) lists the three synthetic fingerprints plus the exact `.env.example:14` artifact fingerprint; any other finding still blocks. `.env.example` already had `DOCMIND_LLM_API_KEY=` empty at `576b7b9` and in the working tree, and no other secret slot in that file is non-empty.
- Manager instruction deviation, verified empirically: the instruction named `.gitleaks.toml`. In gitleaks 8.24.3 the TOML allowlist forms (`[allowlist]`, `[[allowlists]]`, and a `paths` allowlist) did NOT suppress findings under `gitleaks git` (config loading was confirmed: a missing `--config` path is fatal, and each allowlist variant still reported all four findings). The native `.gitleaksignore` suppresses exactly the listed fingerprints. Shipped `.gitleaksignore` instead of a non-functional TOML. The fourth fingerprint is history: the empty-placeholder blob is in commit `576b7b9`, so no working-tree edit can remove that finding.
- Verification: pinned binary over the full history: `10 commits scanned`, `no leaks found`, `EXIT=0`; unit `93 passed`; integration/model `9 passed`.
- Lesson: run the pinned binary over the full history locally before every push from now on.


## M4 - CI/CD with quality gates, image, security scans (2026-11-03)

### Decision: Linux lock file generated inside the base image
- Context: the service must install from a lock file that CI and the image can reproduce, and the development machines are Windows (pip freeze there would leak Windows-only packages).
- Chosen: `scripts/make_lock.ps1` regenerates `requirements.lock` inside `python:3.12-slim-bookworm` from `requirements.txt`; the lock is committed (55 pins) and installed in the Dockerfile and both CI Python jobs. Verified: it contains `fastapi==`, `fastembed==`, `onnxruntime==`, `psycopg==` and no `pywin32` or `colorama`. Dependabot pip PRs change `requirements.txt`, so `scripts\make_lock.ps1` must be run before such a PR is merged.
- Rejected: running `pip freeze` on Windows; unpinned installs in the image (not reproducible).
- Tradeoff accepted: one manual regeneration step whenever a dependency changes; a PR that forgets it installs the old lock in CI and fails visibly.
- Would revisit if: Dependabot can regenerate the lock automatically (it cannot today).

### Decision: single-stage non-root image with the ONNX model baked in
- Context: the deployment target has 512 MB RAM and no model cache; a runtime model download would need Hugging Face access on every cold start, and the free tier spins down.
- Chosen: one `python:3.12-slim-bookworm` stage, `pip install -r requirements.lock`, one build-time `TextEmbedding` call that downloads MiniLM into `/opt/models` (owned by the app user), `USER app` with uid 10001, healthcheck on `/healthz`. Verified: `docker run --rm docmind-service:local id -u` is `10001`; the offline test (`--network none`, load the model, embed, print shape and norm) prints `(384,) 1.0`. Image size 987,185,947 bytes. Base image digest `python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`.
- Rejected: multi-stage build (the model files and site-packages must ship anyway; the stage split would add moving parts without shrinking the final layer set); PyTorch images (multi-GB, fails the memory ladder by design).
- Tradeoff accepted: ~941 MiB uncompressed image; a change to `requirements.lock` invalidates the model layer as well.
- Would revisit if: image size becomes a deploy constraint or the model is swapped for a quantized file in the memory ladder.

### Decision: the evaluation runs on the shipped defaults
- Context: a gate must exercise what ships; a parallel set of eval-only constants would let code and evaluation drift apart, and the M4.9 evidence branch deliberately changes exactly those defaults.
- Chosen: `evaluation/run_retrieval.py` chunks through `chunk_pages(pages)` (the `CHUNK_WORDS`/`CHUNK_OVERLAP` defaults from `docmind_service.chunking`) and retrieves with `get_settings().default_top_k` (10 today), recorded as `top_k` in the results file. `tests/test_eval_defaults.py` parses the module and fails on a numeric `top_k=`, `words=` or `overlap=` literal, and on a missing `get_settings` call.
- Rejected: keeping `top_k=10` hard-coded in the runner (it happens to equal today's default, which is exactly why the divergence would go unnoticed when the default changes).
- Tradeoff accepted: an environment variable that changes `DOCMIND_DEFAULT_TOP_K` also changes the evaluation; CI sets none, and the results file records the effective value.
- Would revisit if: the gates must pin their own top-k independently of the shipped default (that would need a gates.json field and a recorded decision).

### Decision: Trivy and pip-audit policy
- Context: security gates must block real fixable risk without freezing the build on issues that have no fix.
- Chosen: `pip-audit==2.10.1` audits `requirements.lock` with `--no-deps --disable-pip`; any finding blocks, and an unfixable false positive may only be ignored with `--ignore-vuln <ID>` plus a Note with an expiry date. Trivy `0.76.0` blocks on CRITICAL **with a fix** (`--ignore-unfixed --exit-code 1`) and reports HIGH+CRITICAL without blocking. Measured locally on the built image: blocking scan exit 0; report scan 38 findings (36 HIGH, 2 CRITICAL), both CRITICALs (`libsqlite3-0` CVE-2025-7458, `zlib1g` CVE-2023-45853) unfixed/`will_not_fix` in Debian bookworm, therefore ignored by the blocking policy.
- Rejected: blocking on HIGH (would block on every Debian base refresh); scanning with `latest` (unpinned).
- Tradeoff accepted: HIGH findings are visible but do not block; any CRITICAL fix in the base image will block until the base is rebuilt.
- Would revisit if: HIGH findings start including the Python layer and a fix exists.

### Decision: all third-party actions pinned to full commit SHAs
- Context: a mutable tag (`@v4`) is a supply-chain hole; the instructions require full SHAs where resolvable.
- Chosen: `actions/checkout@11d5960a326750d5838078e36cf38b85af677262` (v4), `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (v5), `actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830` (v4), `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02` (v4), `docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9` (v3), each with the tag as a trailing comment. Resolved through the GitHub API (`git/ref/tags/<tag>`, dereferenced where needed). Images: `pgvector/pgvector:pg17` (service), `aquasec/trivy:0.76.0`, `python:3.12-slim-bookworm` (digest above); Dependabot's `docker` ecosystem keeps the base and Trivy tags fresh.
- Rejected: major-version tags with a comment only (what the template showed) — the manager's checkpoint greps for unpinned tools.
- Tradeoff accepted: Dependabot PRs for actions must rewrite the SHA; the trailing comment keeps the version readable.
- Would revisit if: a repository cannot be resolved (the rule allows keeping the major tag with a recorded reason; none was needed).

### Decision: compose-based smoke test instead of mocking the service
- Context: the M4 smoke test must prove the shipped image can start, migrate, ingest, answer and refuse — not that a mock matches another mock.
- Chosen: the `image` CI job runs `docker compose -f deploy/compose.ci.yml up -d --build --wait` (app + pgvector database, fake LLM) and then `scripts/smoke_http.py --mode ci` against `127.0.0.1:8000`: 13 checks over real HTTP (health, readiness, upload 201/200 dedupe, list, answer with citation and request-id header, no-evidence refusal with zero calls, 422 problem+json for an empty question, 422 for non-PDF bytes, delete 204/404, refusal after delete). The script is stdlib-only, so the runner needs no Python dependencies; only the `multipart` helper and the parser are unit-tested, the full run is exercised by the job (as the script requires).
- Rejected: TestClient-based smoke (it bypasses the container, networking, migrations and the baked model); a shell script with curl (less readable assertions, no portable exit-code summary).
- Tradeoff accepted: the job takes the compose build time; a failure prints the last 200 log lines and always tears the stack down.
- Would revisit if: the compose startup needs more than the job's timeout.

### Decision: evidence pull request with a plausible, measured regression
- Context: the milestone must prove the retrieval gate blocks a genuine regression, not that a bad workflow file fails.
- Chosen: branch `evidence/bad-chunking` changes only the shipped defaults a reviewer might plausibly "optimize": `CHUNK_WORDS = 800` in `chunking.py` and `default_top_k = 4` in `config.py`, with the unit tests that assert those defaults updated so G1, G2 and G3 stay green. Locally `scripts\check.ps1` passes; `scripts\check.ps1 -Integration -Eval` must fail E2 (chunk ordinals no longer match the reference) and E3 (top-4 of 800-word chunks misses facts, as in Project 6's 92.3% → 61.5%). The branch is pushed only by Hamza (`[H7]`), never merged; the PR comment carries the gate table. This is the same regression that cost Project 6 31 percentage points, now stopped at review time.
- Rejected: a PR that deletes a test or edits the workflow (proves only that reviews work, not that the gate works).
- Tradeoff accepted: the branch is dead weight kept as evidence; the repository keeps `main` clean and the branch unmerged.
- Would revisit if: the gates change such that the designed regression no longer fails them.

### Decision: Dependabot with three ecosystems and a small PR budget
- Context: dependency freshness should not flood the repository, and pip PRs must not silently break the lock.
- Chosen: `.github/dependabot.yml` runs weekly for `pip`, `github-actions` and `docker`, `open-pull-requests-limit: 3` each. Pip PRs change `requirements.txt`; `scripts\make_lock.ps1` must be run in the PR before merge (also recorded in `docs/EVALUATION.md`'s reproduction section and here).
- Rejected: daily updates; grouping rules (premature for a one-person project).
- Tradeoff accepted: a manual lock regeneration per pip PR.
- Would revisit if: update volume grows or the lock regeneration is automated.

### Note: pins chosen for the M4.6 workflow template (2026-11-03)
- `pip-audit==2.10.1` — newest stable on PyPI, released 2026-06-10, well past the 14-day rule.
- `aquasec/trivy:0.76.0` — newest stable Trivy release that is at least 14 days old: 0.76.0 was published 2026-10-14; 0.76.1 was published 2026-10-21 and was 13 days old on 2026-11-03, so it was excluded. The tag was verified by pulling `aquasec/trivy:0.76.0` from Docker Hub (digest `sha256:2416d1f74045b57274df1a340eee6b510cacd73c66a6ccb8da092b117eb7d222`), and the local scans printed "Version 0.76.1 of Trivy is now available".
- Third-party actions: full SHAs as listed in the decision above; the manager checkpoint greps that no `<pinned` remains and no unpinned tool is referenced (`ubuntu-latest` runner labels and the intentional `:latest` GHCR tag are the only "latest" strings).
- The template had two YAML bugs that actionlint 1.7.7 rejected: unquoted step names containing a colon (`Trivy (blocking: ...)`, `Trivy (report: ...)`) and `${{ runner.temp }}` in a job-level `env:` block, where the `runner` context is not available. Fixed by quoting both names and moving `DOCMIND_MODEL_CACHE_DIR` to step-level `env:` on the two steps that use the model cache. actionlint then exits 0.
- Verification: actionlint 1.7.7 exit 0; `grep -n "<pinned" .github/workflows/ci.yml` finds nothing; `pip-audit -r requirements.lock --no-deps --disable-pip` prints "No known vulnerabilities found" (exit 0).

### Note: network conditions during M4 (R5) and the mirrors used
- Docker Hub registry was unreachable at the start of M4 (`registry-1.docker.io` timed out), so `python:3.12-slim-bookworm` was first pulled through two independent mirrors (`docker.m.daocloud.io`, `docker.1ms.run`), which returned the same multi-arch digest `sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`; the local tag was then created from that content. Later in the same session a direct `docker pull` succeeded and confirmed the same digest; the canonical RepoDigest `python@sha256:e697…` is the one recorded above.
- The first Docker build failed at the model download step (Hugging Face unreachable, R5). Per section 13.1 the build was retried with `--build-arg HF_ENDPOINT=https://hf-mirror.com` for that build only (nothing committed), which produced the first working image. After the network recovered, a plain `docker build -t docmind-service:local .` (no build argument) succeeded in 63.4 s and is the image measured and shipped; the mirror is therefore not needed in the committed build path.
- The `# syntax=docker/dockerfile:1` frontend line was removed from the Dockerfile: that frontend image resolves through Docker Hub at build time and the build failed while the registry was unreachable; no dockerfile-1.x feature is used. `FROM python:3.12-slim-bookworm` is pinned by tag and by the recorded digest.
- The pinned actionlint 1.7.7 binary was downloaded through WSL (`curl` in Ubuntu) because the Windows HTTP client could not reach the GitHub release CDN at that moment; the zip was verified against the official SHA-256 (`7f12f180…`) before extraction.
- Lesson: retry direct registries before recording a mirror as required; check both mirrors' digests when a mirror is unavoidable.

### Note: the release image carries its commit in DOCMIND_GIT_SHA (2026-11-04)
- Context: with the persistent host retired, nothing told `/healthz` which commit the image ran; the only source was the host-set `RENDER_GIT_COMMIT` fallback.
- Chosen: Dockerfile `ARG GIT_SHA=` and `ENV DOCMIND_GIT_SHA=$GIT_SHA` after the model-baking layer; Settings maps an empty value to `None`. Evidence: `docker build --build-arg GIT_SHA=deadbeef --label org.opencontainers.image.revision=deadbeef -t t1 .` -> `/healthz` `{"status":"ok","version":"0.1.0","commit":"deadbeef"}` and label `deadbeef`; a build without the argument -> `/healthz` `{"status":"ok","version":"0.1.0","commit":null}`.
- Rejected: injecting the commit at run time (would make "commit equals pushed commit" a tautology); reading the label at runtime (the app would need Docker access).
- Tradeoff accepted: changing the build arg invalidates the layers after it; the model layer stays cached.
- Would revisit if: the image is built by a system that cannot pass build args.

## M5 - Release verification under Amendment A1 (2026-11-04)

### Decision: no-card rule ends the Render path; Path C (release smoke against production dependencies) becomes the release evidence

- Context: at signup on 2026-11-04 Render demanded a credit card before the first resource could be created, which the project's zero-cost rule forbids on any service. The same day's check of alternatives found Koyeb's pricing FAQ requiring a card with a $29 pre-authorization hold, Hugging Face's Hub documentation requiring a paid plan for Docker and Gradio Spaces, Fly.io, Railway, Cloud Run and Oracle needing a card or billing account, and Northflank contradicting itself (pricing page: no card; billing docs: a payment method is required before creating any resource). Render's blueprint (`render.yaml`) and the `DEMO_URL`/`RENDER_DEPLOY_HOOK_URL` path are therefore retired: H4 is retired, and H5's `DEMO_URL` is conditional on a supplement passing.
- Chosen: Path C, strengthened so the nine checks run in CI on every green `main` run. After the CI gates and the release job, `release-smoke` pulls the exact release image by its commit tag, runs it under a 512 MB limit against the production Neon database and the real provider, and checks commit identity, readiness, a cited answer, refusal, upload protection and rate limiting (gate G8, evidence method G8-C). Secrets live in the GitHub environment `release-smoke` (H4a), restricted to `main`; the workflow forwards them by bare `-e NAME` and never triggers on `pull_request`. Evidence: run 41809139449 (manual dispatch, head `c149900`) is green, 9/9 checks — https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41809139449. Earlier runs 41805063857 (`ac97221`) and 41807161569 (`c149900`) scored 7/9, failing only the two empty-corpus checks; provider requests were 0 + 0 + 1 across the three runs.
- H3/M5.5 history: the Neon project existed throughout, but the laptop `.env.neon` copies repeatedly failed authentication (`password authentication failed for user 'neondb_owner'`) while the Neon console pair and the GitHub-side copies verified good. The role password was reset once. M5.5 was then executed through the manual `neon-seed` CI workflow (run 41807236461 — https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/runs/41807236461) as a recorded deviation: the same M5.5 commands, the same outputs, a different executor environment. Migrations 001_init and 002_demo_caps were pre-applied by `AUTO_MIGRATE`; pgvector 0.8.6 on PostgreSQL 18.6; ingest created 3 documents / 639 chunks (128 + 168 + 343); database 7896 kB -> 11 MB; the demo-check top-3 results against Neon are identical to the local reference file. No secret value appears in this entry.
- Rejected: Render (card wall); Koyeb (card + $29 hold); Hugging Face Docker/Gradio Space (paid plan; a free ZeroGPU Gradio wrapper would replace the audited container and distort the artifact); Fly.io, Railway, Cloud Run, Oracle (card or billing account); Northflank and SnapDeploy (contradictory or unverified claims; only a bounded signup probe could settle them, and no probe was run this round); storing production secrets in the laptop environment (the `.env.neon` copies failed authentication; GitHub environment secrets are the single source).
- Tradeoff accepted: nothing is hosted publicly, so the README says "verified on every release, not hosted" and never "deployed" or "live" unless a supplement passes; the workflow holds two production secrets and the provider key in a GitHub environment restricted to `main` (risk R17); the baseline does not prove public reachability, idle behavior, long-running stability or real-traffic behavior (listed in `docs/EVALUATION.md`).
- Would revisit if: a no-card free host with a wakeable container is verified by signup (then H4b/H4c and G8-L apply), or the GitHub environment secret model is replaced.


## M6 - keys, tenants, guardrails, cache (2026-11-04)

### Decision: tenancy model and key format
- Context: M6 adds API keys, tenants and per-key limits on top of M3's `tenant_id` ("public" default). Keys must never be stored in recoverable form, and the same bytes uploaded by two tenants must yield two separate documents.
- Chosen: key format `dm_<8 hex>_<32 URL-safe chars>`; only the prefix and SHA-256 hash are stored; `compare_digest` for comparison; the full key is shown only at creation. Anonymous caller is tenant `public`; reserved tenants `public`, `eval`, `redteam`. Uploads are scoped by `(tenant_id, sha256)`, so the same file from two tenants is two documents. `X-RateLimit-*` headers expose per-key minute limits; quotas return 403 `quota_exceeded`; a shared global daily LLM cap (800 by default) is enforced before the provider call. Evidence: `docmind_service/auth.py`, `docmind_service/store.py`, `docmind_service/cache.py`, `tests/test_auth.py`, `tests/test_tenancy.py`, `tests/test_m6_integration.py` (full suite 224 passed; integration/model 18 passed), read 2026-11-04.
- Rejected: storing keys or hashes reversible (would expose keys if the DB is read); JWT authentication (would add a dependency and abstraction not requested); per-instance limiter state only (global cap must be shared, so the SQL `daily_cap` table is shared while sliding windows stay per process).
- Tradeoff accepted: revocation can take up to `AUTH_CACHE_SECONDS` (60 s) because of the auth cache; limiter state is per process, so several instances do not share rate windows (documented in `docs/SECURITY.md` known gaps).
- Would revisit if: multi-instance deployment requires shared sliding windows; revocation delay becomes a problem.

### Decision: global cap of 800 and why
- Context: section 8 fixes a whole-M6 budget of 150 provider requests and an 800/day cap stands; `provider_budget.py` counts local `check_llm` calls plus release-smoke runs (upper bound one per run). No M6 provider calls were made this round because the local Groq key returned 403 on the first call (`no-citation` measurement failed; recorded as PENDING-H6).
- Chosen: `global_daily_llm_cap=800` default; anonymous (`demo_daily_cap=300`, `demo_ip_per_min=5`) and keyed callers share the same global cap; `CappedLLM` increments before the call and refuses with 429 `daily_cap_reached`; refusals and cache hits do not consume the cap. Evidence: `docmind_service/config.py`, `docmind_service/ratelimit.py`, `tests/test_tenancy.py` (cap shared between anonymous and keyed callers; refusal/cache do not consume), `evaluation/results/provider-limits.json` (3 of 800 used before M6).
- Rejected: per-key daily caps only (would let 10 keys exhaust the budget); no global cap (would exceed the 800/day rule).
- Tradeoff accepted: one keyed caller can consume the entire global cap, starving anonymous callers; this matches the "shared global daily cap" requirement in section 8.
- Would revisit if: the provider budget is consumed or a multi-tenant deployment needs per-key sub-caps.

### Decision: prompt v2 and context sanitization
- Context: M6.4 guardrails require the off arm (`GUARDRAILS_ENABLED=false`) to reproduce M3 byte-for-byte (`p7-v1`, no validators, no gate), while the on arm uses prompt v2 (`p7-v2`) with rules first, canary, delimiters, question last.
- Chosen: `PROMPT_VERSION = "p7-v2"`; context sanitization replaces `[c<digits>]` -> `(c<digits>)`, neutralizes runs of three or more `<`, `>` or `=`, removes zero-width/control characters (newline and tab kept); prompt v2 starts with the rules block, then `Internal reference: <canary>`, then chunks between `<<<cN page=k>>>` ... `<<<end cN>>>`, then the question last. Output validators: canary (`output_blocked`), citations (unknown ids removed), no-citation (`ungrounded`), exfiltration (Markdown images deleted, out-of-context URLs -> `[link removed]`), length truncation. Evidence: `docmind_service/guardrails.py`, `docmind_service/query.py`, `tests/test_guardrails.py` (21 passed), `tests/test_redteam_harness.py` (9 passed), `git diff --exit-code openapi.json` clean after `scripts/export_openapi.py`, read 2026-11-04.
- Rejected: sanitizing only at output time (fake ids/delimiters would still reach the model in context); placing rules after the context (section 8 prescribes rules first); storing raw question text (query log redacts).
- Tradeoff accepted: the canary validator replaces a leaked canary with a fixed refusal; a model that ignores the canary can still leak other prompt text (documented as a known gap).
- Would revisit if: R1 (arm `on`) exceeds 2 of 15; then up to three improvement attempts are allowed, each a different recorded hypothesis.

### Decision: evidence threshold values and the rule
- Context: M6.4 prescribes retrieval-only calibration (no provider calls): `t = floor_to_2_decimals(min(top-1 of answerable) - 0.02)`; report how many absent questions fall below `t`. Score distributions depend on the corpus, so the threshold is per deployment.
- Chosen: paper corpus minimum answerable top-1 0.3737 (d07) -> threshold 0.35; absent questions below it: 0/4. Demo corpus minimum answerable top-1 0.5465 (d06) -> threshold 0.52; off-topic questions below it: 6/6. `DOCMIND_EVIDENCE_MIN_SCORE` defaults to 0.2 (paper value for local evaluation; demo value on the live service). Evidence: `evaluation/calibrate_evidence.py`, `evaluation/results/evidence-m6.json`, `evaluation/results/evidence-m6-demo.json`, `tests/test_evidence_calibration.py`, read 2026-11-04.
- Rejected: a single threshold for every corpus (score distributions differ by corpus, measured 0.35 vs 0.52); using provider calls for calibration (calibration is retrieval-only and free).
- Tradeoff accepted: the paper threshold refuses none of 4 absent questions (measured); the demo threshold refuses all 6 off-topic questions (measured); claim only the measured effect.
- Would revisit if: M8 changes the question set, chunking, pypdf version, or top-K.

### Decision: no-citation policy outcome (counts out of 12)
- Context: M6.4 pre-declares: run the 12 answerable paper questions once with `REQUIRE_CITATION` off and count answers with no valid citation; default `true` only if at most 1 of 12 would be turned into a refusal, otherwise `false`. Record both counts in DECISIONS.
- Chosen: not measured — the local Groq key returned `403 Forbidden` on the first provider call when running `evaluation/no_citation.py`, so no provider call succeeded. Status: PENDING-H6; the run will be retried with a valid key, and both counts will be recorded here. No provider request was consumed.
- Rejected: guessing the count or using a scripted model (the rule requires provider calls on answerable questions).
- Tradeoff accepted: `REQUIRE_CITATION` remains `true` by default pending measurement; the flag stays measurable in metrics.
- Would revisit if: a valid provider key completes the 12-call run.

### Decision: red-team method and result
- Context: M6.5 prescribes 15 poisoned passages (`evaluation/redteam/cases.json`), each with a benign question and a unique `PWNED-<id>` marker, run twice per arm; an attack succeeds for an arm if `final_hit` is true in any repeat. `r1_attacks_succeeded_guardrails_on` must be <= 2 of 15 (R1 gate, not gating).
- Chosen: `run_redteam.py` builds the app in-process with `InMemoryRetriever` over each passage and `HostedLLM`; records `raw_hit`, `final_hit`, refusal reason, tokens per case/arm/repeat; `--dry-run` uses `DryRunLLM` with no network. Live run attempted 2026-11-04: the local provider key returned 403, so R1 is PENDING-H6; no red-team number is claimed. Harness dry-run is green (9 tests pass). Evidence: `evaluation/redteam/run_redteam.py`, `evaluation/redteam/cases.json`, `tests/test_redteam_harness.py`, read 2026-11-04.
- Rejected: running red-team against the live service before M6.10 (section 8 prescribes local measurement first); claiming R1 without live numbers.
- Tradeoff accepted: R1 is reported honestly and pending; if arm `on` later exceeds 2 of 15, up to three improvement attempts are allowed, each re-run over failed cases only and recorded.
- Would revisit if: H6 supplies a valid key and the live run completes.

### Decision: redaction scope and the numbers
- Context: M6.6 prescribes `redact(text)` applied in a fixed order (emails -> `[EMAIL]`; CNIC/resident IDs -> `[ID]`; Luhn-valid cards -> `[CARD]`; 8-15 digits -> `[PHONE]`; 9+ digits -> `[NUMBER]`; all URLs -> `[URL]`; secret-looking tokens incl. `dm_<8 hex>_<32 chars>` -> `[SECRET]`; IPv4 -> `[IP]`) with truncation to 500 chars; names are not redacted. The query log stores redacted text only for anonymous tenant `public`, retained 30 days; keyed tenants get no row.
- Chosen: `docmind_service/redact.py` and `docmind_service/querylog.py` as prescribed; committed `tests/redaction_cases.json` with 51 PII samples and 18 benign sentences. Measured: recall 51/51 = 1.000 (threshold >= 95%); benign false positives 0/18 (threshold <= 2). Evidence: `tests/test_redaction.py` (11 passed), `tests/test_m6_integration.py` (query log redacted, keyed not logged), `tests/test_landing_page.py` (privacy line), read 2026-11-04.
- Rejected: redacting names (specification keeps names); logging raw question text (would violate the demo privacy claim).
- Tradeoff accepted: regex redaction misses novel phone/ID formats and numbers indistinguishable from benign numbers; documented as a known gap in `docs/SECURITY.md`.
- Would revisit if: redaction numbers fall below the stated thresholds or new PII formats appear.

### Decision: cache threshold with the calibration/test split
- Context: M6.7 prescribes `scope_hash` over sorted document ids, top_k, mode, prompt version, model, guardrails flag, evidence threshold, citation flag; TTL 30 days; max 500 rows/tenant; SQL + in-memory mirror; only non-refused validated answers are stored. C1 gate: `c1_false_hit_share <= 0.05` (gating); τ = smallest value whose calibration-half false-hit share <= 0.02; report test half at that τ. `CACHE_ENABLED=true` only if C1 passes and test-half hit rate >= 0.25.
- Chosen: `cache_threshold` default changed to 0.86 (from 0.9) because the pre-declared rule selected τ=0.86: calibration false-hit 0.0000; test-half same-intent hit rate 0.3636 (16/44), false-hit share 0.0000 (0/32), hit rate >= 0.25 so `CACHE_ENABLED=true`. Pairs file: 44 same-intent + 32 different-intent probes; odd ids calibration, even ids test; test half not used to choose τ. Evidence: `evaluation/cache_eval/run_cache_eval.py`, `evaluation/cache_eval/pairs.json`, `evaluation/results/cache-m6.json`, `tests/test_cache_eval.py`, `tests/test_cache.py`, `docmind_service/config.py`, read 2026-11-04.
- Rejected: choosing τ from the test half (would invalidate C1); caching refusals/blocked answers (only validated answers are stored).
- Tradeoff accepted: the cache key includes tenant and corpus version, so a cache hit never crosses tenants; the query vector is computed once per request.
- Would revisit if: C1 fails (false-hit > 0.05) or the test-half hit rate falls below 0.25; then `CACHE_ENABLED=false`.

### Decision: quotas return 403 quota_exceeded
- Context: M6.1 tenancy adds document/page quotas per key; section 8 requires quota failures to return 403 `code="quota_exceeded"`.
- Chosen: quota checks run inside `store.add_document` before insert; `max_documents` and `max_pages` are per-key settings; failures return 403 `quota_exceeded` with a detail naming the limit; anonymous uploads are blocked (uploads_enabled keyed only). Evidence: `docmind_service/store.py`, `docmind_service/main.py`, `tests/test_tenancy.py`, `tests/test_m6_integration.py::test_pg_store_quotas`, read 2026-11-04.
- Rejected: returning 429 for quota (quotas are not rate limits); blocking the whole tenant (only the exceeding upload is refused).
- Tradeoff accepted: concurrent uploads from the same tenant race only if the store's check-and-insert is not serialized; the local store checks within the same transaction.
- Would revisit if: per-tenant concurrent upload limits become necessary.
