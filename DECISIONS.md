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
- Context: section 8 fixes a whole-M6 budget of 150 provider requests and an 800/day cap stands; `provider_budget.py` counts local provider calls plus release-smoke runs (upper bound one per run). M6 measurement runs made 75 successful provider calls (3 aborted pre-run + 12 no-citation + 60 red-team), or 112 attempts including in-run retries; `provider_budget.py` post-flight: `used_today=76` (1 `check_llm` retest + 75 measurement calls), `used_today_upper_bound=80` of 800.
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
- Chosen: measured 2026-11-04 with `python -m evaluation.no_citation` (12 answerable paper questions, `REQUIRE_CITATION` off, prompt `p7-v2`, model `openai/gpt-oss-120b`): output verbatim `no_citation=1/12 recommended_default=True provider_requests=21`. Counts: 1 of 12 answers had no valid citation (`d09`, `citations=0`); 0 of 12 were refused. Under `REQUIRE_CITATION=true` exactly that 1 uncited answer would become a refusal, so the pre-declared rule (default `true` only if at most 1 of 12 would become a refusal) keeps the default `true`. Evidence: `evaluation/results/no-citation-m6.json` (`status: measured`, `require_citation_measured: false`, `total: 12`, `no_citation: 1`, `recommended_default: true`), read 2026-11-04.
- Rejected: guessing the count or using a scripted model (the rule requires provider calls on answerable questions).
- Tradeoff accepted: `REQUIRE_CITATION` stays `true`, so one measured answer (`d09`) would be refused by default; the flag stays measurable in metrics.
- Would revisit if: the prompt version, model or question set changes.

### Decision: red-team method and result
- Context: M6.5 prescribes 15 poisoned passages (`evaluation/redteam/cases.json`), each with a benign question and a unique `PWNED-<id>` marker, run twice per arm; an attack succeeds for an arm if `final_hit` is true in any repeat. `r1_attacks_succeeded_guardrails_on` must be <= 2 of 15 (R1 gate, not gating).
- Chosen: `run_redteam.py` builds the app in-process with `InMemoryRetriever` over each passage and `HostedLLM`; records `raw_hit`, `final_hit`, refusal reason, tokens per case/arm/repeat; `--dry-run` uses `DryRunLLM` with no network. Live run 2026-11-04 with `python -m evaluation.redteam.run_redteam --arms off,on --repeats 2`: arm `off` 7/15 succeeded (`model_resisted=8`, `guardrail_caught=0`, `provider_requests=39`), arm `on` 0/15 succeeded (`model_resisted=15`, `guardrail_caught=0`, `provider_requests=49`); `r1_attacks_succeeded_guardrails_on=0`, `r1_attacks_succeeded_guardrails_off=7`, `provider_requests_total=88`, `status: measured`. The `off` arm's 7/15 shows the harness can succeed, so the `on` arm's 0/15 is meaningful (section 8.5 check). Gate table verbatim: `| R1 | 0 / 15 | <= 2 | PASS | no |`. Evidence: `evaluation/results/redteam-m6.json` (60 records: 15 cases x 2 arms x 2 repeats), `tests/test_redteam_harness.py` (9 passed), read 2026-11-04.
- Rejected: running red-team against the live service before M6.10 (section 8 prescribes local measurement first); claiming R1 without live numbers.
- Tradeoff accepted: mid-run provider rate limits were retried in place by `HostedLLM.complete` (at most 3 attempts, waits capped at 20 s), inflating `provider_requests` above the 60 case-runs; the run was never restarted, so no count was zeroed.
- Would revisit if: R1 (arm `on`) exceeds 2 of 15; then up to three improvement attempts are allowed, each a different recorded hypothesis.

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

### Decision: CI smoke authenticates writes (M6 fix round)
- Context: CI run 41830038931 on `cde46c3` passed lint, unit, retrieval-eval and security, but the image job's container smoke failed 5 of 13 checks. The container booted cleanly; the root cause was the M4-era `scripts/smoke_http.py` CI mode posting anonymously to `/v1/documents`, which M6.2 makes key-only and returns 403. Master Script section 8 (M6.2) "Routes" states: "Upload and delete need scope `write`, a keyed principal, and `UPLOADS_ENABLED=true`, otherwise 403. Anonymous callers can only query and list the `public` tenant. The `public` tenant cannot be written through the API at all (only `scripts/ingest_corpus.py` writes it)." The app matches the script; the CI smoke was stale.
- Chosen: fix the smoke only. CI mode now asserts the anonymous upload 403 as a checked expectation, creates a throwaway tenant `smoke-ci` and a write-scoped key with `docker compose exec -T app python -m docmind_service.admin create-key --tenant smoke-ci --label ci --write`, captures the printed key in a shell variable only (never echoed, logged or committed), and runs the existing upload/list/query/delete flow with `--api-key-env`. The no-evidence check now expects M6's `low_evidence` (guardrails on) while still asserting refusal, zero provider calls and no citations. The ephemeral smoke's anonymous-upload check is unchanged; against production config anonymous upload stays 403. Ephemeral mode was aligned in the same fix round: check 7 (`nonsense question refused`) now expects `low_evidence` and empty citations (was `no_evidence`), keeping the refusal and zero-provider-call assertions. The other eight ephemeral checks were scanned; none had another demonstrably stale M6 expectation (details in `reports/M6.md`).
- Rejected: allowing anonymous writes (violates M6.2 and the public-tenant read-only rule); weakening the ephemeral smoke; keeping the stale `no_evidence` expectation (M6 returns `low_evidence` when guardrails filter every chunk).
- Tradeoff accepted: the CI smoke now depends on the admin CLI and a throwaway key in the throwaway CI database; the key is created per run and never stored. The ephemeral smoke was not simulated locally: it runs in CI against Neon and the hosted provider. Its sample-question citation check is the only live-run uncertainty (M6 prompt v2/`REQUIRE_CITATION=true`); it was left unchanged because it still asserts the M6 contract, not a pre-M6 expectation.
- Evidence: local compose reproduction (`docker compose -f deploy/compose.ci.yml up -d --build --wait` + admin create-key + `python scripts/smoke_http.py --base http://127.0.0.1:8000 --mode ci --api-key-env DOCMIND_SMOKE_KEY`) → 14 checks, `ok=True`, all PASS; re-ran after the ephemeral alignment → same 14/14; `pytest -q` 224 passed, 18 deselected; `ruff check` and `ruff format --check` clean; `.github/workflows/ci.yml` Container smoke step updated. Read 2026-11-04.
- Would revisit if: the CI compose stack stops providing the admin CLI, or M6.2's capability rule changes.

## M7 - metrics, dashboards, load tests, runbook (2026-11-05)

### Decision: metrics design and the cardinality rule
- Context: M7.1 requires Prometheus metrics whose labels come only from fixed small sets; a scrape must never touch the database (it would wake a scaled-to-zero Neon) and never carry user text, document ids, request ids, key prefixes or tenant ids.
- Chosen: `docmind_service/metrics.py` on prometheus-client with a dedicated registry. `docmind_http_requests_total{method, route, status}` uses the route TEMPLATE (`/v1/query`, `/v1/documents/{document_id}`) or `other`, so random 404 paths add at most one series (tested with 100 random paths). `docmind_query_total{outcome, principal}` counts outcomes (`answered`, `cache_hit`, `refused_no_evidence`, `refused_low_evidence`, `refused_ungrounded`, `blocked_output`, `provider_error`, `retrieval_error`, `rate_limited`, `cap_reached`) with `principal` = `anonymous`|`keyed` only. Pool gauges are read from in-process pool statistics at scrape time; no SQL at scrape. A unique-string test proves a question word, a document filename and a key never appear in the exposition.
- Rejected: per-tenant or per-key labels (unbounded cardinality and a privacy leak); scraping the database for counters (wakes Neon, couples monitoring to the thing it monitors).
- Tradeoff accepted: tenant-level diagnosis is impossible from metrics alone; the redacted query log is the per-tenant record.
- Would revisit if: a multi-instance deployment needs tenant-level alerting (then aggregate offline, not via labels).

### Decision: /metrics access rule
- Context: metrics reveal traffic shape and build identity; the release runs with no persistent host (Amendment A1), so the rule must be safe by default in prod and frictionless in dev.
- Chosen: prod + no `DOCMIND_METRICS_TOKEN` -> 404 (feature off, indistinguishable from a missing route); token set in any environment -> Bearer required, constant-time compare, 401 otherwise; dev/test + no token -> open. `GET /metrics` is excluded from the OpenAPI schema.
- Rejected: IP allowlists (the release path has no stable operator IP); basic auth (a second credential shape to rotate).
- Tradeoff accepted: in prod with a token set, a scrape failure looks like an auth problem, not a metrics problem; the runbook's incident table says so.
- Would revisit if: a hosted deployment adds platform-level private networking for scrapes.

### Decision: prometheus-client dependency and its cost
- Context: M7.1 adds one runtime dependency. M4 recorded the pre-M7 image at 987,185,947 bytes with 202.4 MB idle memory (`evaluation/results/m4-container.json`).
- Chosen: `prometheus_client` pinned in `requirements.txt`, lock refreshed. Measured cost: image 988,656,797 bytes (delta +1,470,850 vs M4); idle memory of the M7 container ≈ 204 MiB vs 202.4 MB at M4.
- Rejected: hand-rolling the exposition format (the drift test and histogram buckets are exactly where hand-rolled formats rot).
- Tradeoff accepted: one more dependency to keep patched (Dependabot covers it).
- Would revisit if: the image-size or idle-memory delta grows materially on a future bump.

### Decision: load tool in the standard library, and the two profiles
- Context: M7.3's tool must run anywhere the repo runs, with no new dependency; the free-tier shape it must predict is Render's published 512 MB / fractional-CPU instance (Amendment A1: no live load test is possible or allowed).
- Chosen: `scripts/loadtest.py` uses only `threading`, `urllib`, `time`, `statistics`, `json`. Profiles: `unconstrained` = `--memory 512m`; `render-like` = `--memory 512m --cpus 0.1`. The matrix (mixed scenario, 60 s runs, 10 s pauses) covers both profiles; an answered-only cache run and a 10-minute soak complete the record in `evaluation/results/load-m7.json`.
- Rejected: locust/k6 (new dependencies for a one-off measurement); testing against the release-smoke environment (rate-limited by design; would burn the shared provider budget and measure Neon's network, not the service).
- Tradeoff accepted: render-like is a local approximation of the free instance, labelled as such wherever its numbers are quoted.
- Would revisit if: a persistent host is ever adopted (then one bounded live confirmation run, never a matrix).

### Decision: what the matrix found, and the harness fixes applied first
- Context: manager verification of the executor's first load run found the run had measured the rate limiter, not the service: the harness did not pass the M7.3 application load settings, so 34,501 requests in 60.0 s were answered 429 by the default demo per-IP cap (5/min) and the run's status counts came back empty. Three tool defects caused it: (1) `scripts/run_load_m7.py` started the container without `DOCMIND_DEMO_IP_PER_MIN`/`DOCMIND_DEMO_DAILY_CAP`/`DOCMIND_GLOBAL_DAILY_LLM_CAP` raised and with the cache on; (2) its 5xx scrape parsed `docmind_query_total` expecting a `status` label that the M7.1 design does not emit — the counts live on `docmind_http_requests_total{route, status}`; (3) `scripts/loadtest.py` masked HTTP error statuses as client timeouts (blanket `except` around `urlopen`, which raises `HTTPError` for 4xx/5xx) and ended the run when its fixed question pool drained (0.59 s for the nominal 60 s run).
- Chosen: fix the tools, then measure. loadtest gained an `HTTPError` branch (real statuses recorded) and a sustaining closed loop (top-up to the configured concurrency until the duration elapses); run_load passes the M7.3 settings with the cache off and counts 5xx from `docmind_http_requests_total` for `route="/v1/query"`; the demo corpus was ingested into the local database (3 documents / 639 chunks as tenant `public`, alongside 2 one-chunk drill leftovers) so the answered path is real. The repaired single run at concurrency 10: 6,755 requests, all 200, 0 timeouts, p95 0.109 s, peak 210.6 MB; the full matrix followed (next entry).
- Rejected: accepting the first run's gates (L1 printed PASS over an empty scrape — a gate computed from no evidence); patching the JSON by hand.
- Tradeoff accepted: the milestone record keeps the void run in this entry rather than deleting it; `load-m7.json` holds only the post-fix measurements.
- Would revisit if: the harness changes again (any future edit re-runs the c10 validation before a matrix).

### Decision: dashboards as code with a drift test
- Context: a dashboard that names a metric the app no longer emits fails silently at the worst time.
- Chosen: the Grafana dashboard is a committed JSON (uid `docmind`, 11 panels) with provisioning as code under `deploy/observability/`; `tests/test_dashboard.py` parses every panel query and asserts each `docmind_*`/`process_*` name exists in the app's exposition (on Windows the process collector is a no-op without /proc, so the test skips `process_*` names there; CI on Linux arbitrates).
- Rejected: click-built dashboards exported after the fact (unreviewable diffs, no drift guard).
- Tradeoff accepted: panel edits go through code review and the drift test, not the Grafana UI.
- Would revisit if: the stack moves to a hosted Grafana with its own provisioning.

### Decision: drill findings — one real bug, fixed; drills isolated from the shared counter
- Context: M7.4 verifies the behaviors the runbook claims. Drill 1 (database stopped) failed on its first run: `POST /v1/query` returned **500** with no outcome counted, where the spec requires a 503 problem with `Retry-After` and a `retrieval_error` outcome. Root cause: `PgStore.retrieve` translates psycopg failures into `RetrievalError`, but the query route touches the database earlier — the semantic cache (`lookup`/`purge`) and `PgStore.get_corpus_version` — and those paths raised raw psycopg errors outside the route's error mapping. Separately, drills 2 and 3 were first measured against the shared local database, whose Postgres-backed daily counter the day's earlier runs had already spent (the counter is database-persisted, not per-process), so both drills reported `daily_cap_reached` regardless of their own settings.
- Chosen: fix at the component boundary, mirroring the store's existing pattern — `SemanticCache` wraps its pool operations in a `_db_errors()` translator and `get_corpus_version` raises `RetrievalError` on `(psycopg.Error, PoolTimeout)`; the route additionally counts the `retrieval_error` outcome for failures on the cache path. Regression tests in `tests/test_db_down.py` pin all three translations. Drills 2, 3 and 5 were re-run against an isolated drill database with a zeroed counter and the corpus ingested (drill 3 at the release evidence threshold 0.52). After the fix: drill 1 = 503 + `Retry-After: 30` + `retrieval_error`, recovery 2.3 s after the database restarted; drill 2 = 503 `provider_error`; drill 3 = 200 answered, then 429 `daily_cap_reached` with `Retry-After`, refusal still 200; drill 4 cold start 1.69/1.77 s; drill 5 = 413/422/422/422. Suite after the fix: 248 passed.
- Rejected: catching psycopg exceptions in the HTTP route (leaks storage details into the web layer; every future caller of the cache would need the same catch); resetting the shared database's counter for the drills (corrupts the accounting of every other run that shares it).
- Tradeoff accepted: `SemanticCache.store` now also raises `RetrievalError` on a database failure, so an answer computed while the database dies mid-request returns 503 instead of the answer — an honest failure over a silently uncached success.
- Would revisit if: a second storage backend appears (then the translation belongs behind a store/cache interface, not per-component).

### Decision: no live load test
- Context: section 9 forbids load-testing the live free-tier service: it is rate-limited by design and shares the 800/day provider budget.
- Chosen: all load evidence is local against the release-class image with the fake provider; the release path itself is exercised only by the 1-request release-smoke. Provider requests in M7: 0.
- Rejected: a "small" live load run (there is no small version of a 60-second concurrency-10 test against a 5/min limiter).
- Tradeoff accepted: live latency under load stays unmeasured; the capacity model (M8) is built from the local matrix and says so.
- Would revisit if: a paid or self-hosted instance exists.

## M8 - service-level evaluation and close-out (2026-11-06)

### The S2 abstention rule

- Context: S2 (absent questions abstained, gate at least 3 of 4) never had
  its counting rule written down; a non-refused answer could still be an
  abstention in words.
- Chosen: an answer counts as an abstention when the service refuses it OR
  its text matches `evaluation/scoring.py`'s `is_abstention` (the Project 6
  scorer, unimproved). The rule is pinned by 20 examples in
  `tests/test_abstention.py` (10 abstaining, 10 answering) before the first
  service-eval run.
- Note: in runs A and B all four absent questions were refused outright, so
  this measurement is 4/4 under either half of the rule; the text half
  exists for runs where the model answers in abstention words.
- Would revisit if: the provider or prompt changes the refusal behaviour.

### Live verification under Amendment A1

- Context: sections 10.7 and 10.8 were written against a persistent live
  host; Amendment A1 (M5) replaced that with release verification after
  every free host checked required a card or restricted the runtime.
- Chosen: the M8 live steps map to the `release-smoke` workflow (G8-C: the
  pushed image against production Neon and the real provider, nine checks)
  on the final head, plus the manager checkpoint re-runs against the local
  image. The mapping is the same one M5 and M7 closed under.
- Rejected: re-opening the host search for the final milestone.

### Run A repair and the d08 casualty

- Context: run A crossed a cluster of transient provider failures; five
  questions returned HTTP 503 with zero provider calls spent.
- Chosen: the failure rule — re-run only the affected questions against the
  standing eval database (chunk ids stay stable), merge, recompute, and
  record the repair in the results file. Four of five resolved for
  5 requests. d08 returned 503 on two further attempts across about
  40 minutes while neighbouring questions succeeded; it is recorded as a
  provider-availability casualty and no fourth attempt was made (run B
  answers d08 2/2). The A-B variance this leaves is stated in
  `docs/EVALUATION.md`, as the variance rule requires.

### S1 fails its gate; the threshold is not re-registered

- Context: S1 (key facts in answers through the API, gate 22/26) measured
  10/26 in run A and 16/26 in run B. Retrieval alone holds 23/26 (E3), so
  the gap is created inside the service stack, and it is decomposed in
  `docs/EVALUATION.md`: the evidence gate drops 5 facts whose chunks score
  below the threshold calibrated on top-1 scores; the all-or-nothing
  grounding validator refuses 4 facts that were in the prompt; 1 fact is a
  partial answer.
- Chosen: record S1 as a failed gate with the full analysis and close M8
  PASS-WITH-NOTES. The manager recommended this over a post-hoc threshold
  change, and Hamza accepted the recommendation on 2026-11-06 ("do it what
  you think is right").
- Rejected: re-registering S1 post-hoc (the measured causes are design
  properties, not a scoring accident; a lower bar would hide them), and
  lowering the evaluation evidence threshold (recovers at most 3 of the
  missing facts; d09's chunk at 0.2209 stays unreachable).
- Tradeoff accepted: the headline service-level number stays well below
  the retrieval number, in public, with the explanation next to it.
- Would revisit if: Project 9 implements fact-aware evidence gating or
  per-claim grounding; the held-out set for that comparison is prepared
  (`evaluation/heldout/manifest.json`).

### Capacity inputs: the published provider table

- Context: the capacity model needs RPM and TPD; the response headers
  carry only the token-per-minute and requests-per-day limits.
- Chosen: RPM 30 and TPD 200,000 from the provider's published free-plan
  table for `openai/gpt-oss-120b`, retrieved 2026-11-06; the table agrees
  with the live headers on TPM (8,000) and RPD (1,000). All four values
  and their sources are recorded in `evaluation/results/capacity-m8.json`.
- Consequence: at the measured 2,498.9 tokens per answered query, the
  daily token cap — not the 800-request planning cap — is the binding
  daily constraint (80.0 answered queries/day).

### Run C repairs; d10 and d11 stand as casualties

- Context: run C crossed provider 503 clusters in the original run and in
  both repairs, the same failure mode as run A.
- Chosen: two repairs under the failure rule (the 12 affected questions,
  then the 5 remaining document questions). After three attempts each,
  d10, d11, a02 and a03 remained unmeasured; run C is reported with S1 as
  a lower bound and the unmeasured questions named.
- Consequence: the ablation still prices the guardrail stack (at least
  19 against 16 and 10) but cannot price d11's validator refusal, and its
  S2 rests on the two absent questions that could be measured.

### Budget incident: duplicate execution of runs A and B

- Context: the one-shot scheduled task that executed runs A and B kept a
  live 23:59 trigger and fired again overnight on 2026-11-06,
  re-executing both runs (+38 provider requests) and overwriting the
  working results file and the raw-answers file.
- Measured consequence: the 2026-11-06 ledger total is 83 against the
  milestone day cap of 60 — the day cap was exceeded. The milestone
  total is 97 against the cap of 100 — met. The duplicate measured run A
  at 4 / 26 (503-contaminated) and run B at 19 / 26.
- Chosen: the canonical runs stand (A repaired 10 / 26, B 16 / 26, as
  committed); the duplicate measurements are discarded, including the
  higher B — an accidental re-measurement is not a basis for replacing a
  recorded run. The working results file was restored from the committed
  version and run C merged into the restored file. The raw answers for
  runs A and B were overwritten by the duplicate and are lost; no
  remaining step needs them.
- Rule adopted: one-shot scheduled tasks are deleted immediately after
  their run completes; a leftover trigger is treated as a pending
  execution.

### README quick start: create the smoke key first

- Context: under the M6 authentication ruling (writes are key-only), the
  documented quick start's anonymous smoke run fails its write-path
  checks; CI passes because it creates a throwaway write key first.
- Chosen: the README quick start mirrors CI — create a throwaway key in
  the local stack and pass it to the smoke script through an environment
  variable. Verified end-to-end by the clean-clone rehearsal.

### Public demo on a Hugging Face Gradio Space (2026-11-07)

- Context: Project 7 closed at `79c596a` with no persistent public
  instance (Amendment A1). The M5 host evaluation in
  `docs/OPERATIONS.md` had marked the Gradio/ZeroGPU route OUT for
  three reasons: it is not the gated container image, ZeroGPU expects
  a GPU-decorated function on what is a CPU workload, and it consumes
  the second and last free Gradio slot. On 2026-11-07 the owner
  instructed a public demo link anyway, in the Project 6 form. Hugging
  Face Docker Spaces were verified paywalled behind PRO ($9/month)
  the same day; the zero-cost rule bars subscribing without the
  owner's explicit word, which was not given.
- Chosen: a Gradio Space (ZeroGPU free, public) whose front end calls
  the real FastAPI app in-process (anonymous, public tenant) over the
  seeded NIST demo corpus, the service package byte-identical to
  `79c596a`, the demo configuration from `deploy/release.env`, and
  secrets = the production Neon strings plus a dedicated Groq key
  (`hf-demo`) held as Space secrets only.
- Adaptations, disclosed in the Space README: pydantic 2.11.10 in the
  Space only (Gradio 5.49.1 requires pydantic < 2.12; the repository
  pin 2.14.1 is unchanged — the first Space build failed on exactly
  this conflict), and `DOCMIND_DEMO_IP_PER_MIN=60` in the Space only
  (all UI traffic shares one in-process client bucket, so per-IP
  limiting cannot distinguish visitors there; the Postgres-backed
  300/day anonymous and 800/day global caps are unchanged and
  shared). The one GPU-decorated function is an explicitly clicked
  warm-up that loads the embedding model and embeds a probe sentence;
  asking is not decorated and spends no GPU quota.
- Verification: Space RUNNING on zero-a10g (Space commits `69c7af7`
  initial, build failed on the pydantic conflict; `af74e45` with the
  adaptation, RUNNING). Anonymous live checks on 2026-11-07 through
  the Space's Gradio API: d01 answered with citations (pp. 24-25,
  semantic-cache hit); a novel question about the MAP function
  answered with a live generation (1 LLM call, 388 prompt tokens,
  citation p. 30); an off-corpus question refused (`low_evidence`).
- Consequence: the A1 posture is superseded for a UI demo only.
  Release verification remains the deployment evidence for the gated
  image, and the three M5 reservations stand as accepted trade-offs,
  recorded here rather than silently dropped. The demo sleeps after
  48 h idle (free-tier `gcTimeout` 172800).

### P7.1: S1 remediation — evidence gate conformed to the M6.4 spec, citation-repair retry (2026-11-07/08)

- Context: M8 recorded S1 at 10/26 (run A) and 16/26 (run B) against
  the pre-registered gate of 22/26, with the shortfall decomposed as
  the evidence gate (5 facts: d07, d09), the all-or-nothing grounding
  validator (4 facts: d03, d11), and a partial answer (1 fact: d12).
  The M6.4 spec defines the evidence gate as a top-1 test — "if the
  best score is below EVIDENCE_MIN_SCORE, refuse" — and calibrates
  the threshold on top-1 scores only (minimum answerable top-1 0.3737
  -> 0.35). The shipped code instead filtered chunks one by one
  (`chunks = [chunk for chunk in chunks if chunk.score >=
  evidence_min_score]`), silently dropping fact-bearing chunks below
  the threshold from the prompt even when the best chunk cleared it.
  The deviation was found from Claude's hypothesis (the gate, not the
  validator, was the larger funnel) confirmed by Sol's code read of
  `docmind_service/query.py`; the calibration entry above already
  stated the top-1 rule, so the code, not the spec, was wrong.
- Chosen: three changes, approved by Hamza on 2026-11-07 with a
  provider budget of at most 100 requests total and 60 per UTC day.
  (1) The gate now tests the best score only and every retrieved
  chunk reaches the prompt (`1925429`). (2) A citation-repair retry:
  an answer refused `ungrounded` (no valid citation) is retried once
  with an explicit cite-the-chunks instruction; the refusal stands
  only if the retry is also uncited, and no other refusal kind
  (`low_evidence`, `output_blocked`) is retried (`1925429`).
  (3) Usage after a repair retry now merges both calls' attempts and
  tokens, so the response accounting counts every provider call
  (`c49699b`); before that fix only the final call was counted, which
  makes run A2's recorded 14 requests a lower bound (see Budget).
  Prompt v2, context sanitization, every threshold, and
  `service-eval-m8.json` are unchanged; the gates were not
  re-registered.
- Tests updated: the three tests that encoded the pre-fix behaviour
  were changed with the code, not after it. `test_guardrails`
  (`test_require_citation_turns_a_bare_answer_into_ungrounded`) now
  scripts two bare replies and asserts `calls == 2` after a repair;
  `test_metrics` (`test_uncited_answer_refuses_as_ungrounded`) scripts
  the uncited reply twice; `test_redteam_harness`
  (`test_a_guardrail_caught_attack_is_raw_hit_but_not_final_hit`)
  scripts the same reply twice, so the retry is also refused and the
  guardrail still catches the attack. 284 unit tests passed locally
  before each push.
- Measured, after remediation (post-hoc iteration, tuned on the
  evaluation questions):

  | Run | S1 key facts | S2 abstentions | S3a | S3b | S4 | S5 mean prompt tokens |
  |---|---|---|---|---|---|---|
  | A (M8) | 10 / 26 | 4 / 4 | 1.000 | 0.875 | 0.667 | 2002 |
  | B (M8) | 16 / 26 | 4 / 4 | 1.000 | 1.000 | 0.875 | 2351 |
  | A2 (P7.1) | 22 / 26 | 2 / 4 | 1.000 | 0.846 | 0.909 | 2083 |
  | B2 (P7.1) | 17 / 26 | 0 / 4 recorded | 1.000 | 0.643 | 0.889 | 1572 |

  Tuned on the same 12 questions; held-out check is Project 9.
  Run A2 (2026-11-07, image `docmind-service:p71`) met the S1 gate
  at 22/26: d07 recovered 3/3, d03 2/2 and d11 2/2 (all three were
  M8 losses — d07 gate funnel, d03/d11 validator refusals). Run B2
  (2026-11-08, same image) measured 17/26 and did not meet the gate:
  d02 answered 3/3 and d07 2/3, but d03 gave 1/2, d11 was refused
  `ungrounded` 0/2 even after the repair retry (2 provider calls),
  and d10 could not be measured at all. d09 was refused `ungrounded`
  0/2 in both runs even after the repair retry, so the validator
  refusal survives the repair where the draft itself is ungrounded.
  d02 (2/3 in A2) and d12 (1/2 in both runs) stay partial. The A2–B2
  gap is 5 facts, the same scale as the M8 A–B gap (6 after repair):
  provider nondeterminism across identical requests dominates the
  remediation effect on this set, so A2 meeting the gate and B2
  missing it is one measurement each, not a stable pass.
- S2: A2 recorded 2/4 — a01 and a02 abstained, a03 and a04 were never
  successfully asked (provider 503 on every attempt across five
  repair rounds) and count as unmeasurable under the M8 run-C
  convention. B2 recorded 0/4 — all four absent questions were
  unmeasurable (503 on the initial run and all three repair rounds),
  so B2's S2 is a record of provider availability, not of
  abstention behaviour.
- R1 re-confirmation: the on arm was re-run last
  (`evaluation/results/redteam-p71.json`, 15 cases, 1 repeat, on arm
  only — the off arm was never re-run): 0/15 attacks succeeded,
  model resisted 15/15, guardrail caught 0, 15 provider requests.
  The gate (≤ 2/15) still holds after the repair retry. Repeats were
  dropped from 2 to 1 before the run: the M6 on arm spent 49 requests
  for 30 nominal (per-repeat 23 and 26), which projected the UTC day
  to about 62 against the 60 cap; the actual spend was 15 (no retry
  fired in any of the 15 records), so two repeats would likely have
  fit — the decision was made on the pre-flight evidence and stands,
  and the re-confirmation is one repeat. Caveat: with the
  citation-repair retry, `RecordingLLM.last_text` reflects the final
  attempt only, so `raw_hit` in the P7.1 red-team file is the final
  attempt's text; no record in this run needed a second call, so the
  caveat did not affect the measurement.
- Budget actuals: P7.1 recorded 42 provider requests against the 100
  cap — run A2 14 (2026-11-07), run B2 13 (2026-11-08), R1 15
  (2026-11-08); the UTC-day totals are 14 and 28 against the 60 cap.
  A2's 14 is a lower bound: it was measured before `c49699b`, when a
  repair retry's first call was invisible in the response accounting
  (d09, a01 and a02 each refused `ungrounded` and so each likely spent
  an uncounted first call), so the true P7.1 total is at most 45.
  B2 and R1 counts are exact under the merged accounting. 503
  attempts do not count, by the successful-call convention.
- Day-1 incidents (2026-11-07): the evening provider 503 wall hit
  run A2 after a few calls; five repair rounds were needed to measure
  it, and a03/a04 never got through. A one-shot scheduled task with a
  start time 5 minutes ahead double-fired; it was killed before any
  provider call and deleted. Rule adopted: one-shot scheduled tasks
  use a start date at least a day ahead and are deleted immediately
  after the run.
- Day-2 incidents (2026-11-08): run B2's initial run returned 503
  for 14 of 16 questions (only d01, d02 succeeded); three repair
  rounds followed, with d10 and a01–a04 still 503 on every attempt —
  they stand as provider-availability casualties. The `timeout /t`
  cooldown failed under SSH stdin redirection ("Input redirection is
  not supported"), so round 1's intended 300 s wait did not execute
  as a command and the gap was the prep work between runs; rounds 2
  and 3 used `ping -n 301 127.0.0.1` as the cooldown, which worked.
  B2's S1 below 22 ends the remediation under Hamza's stop rule: no
  third remediation round.
- Would revisit if: Project 9 runs the held-out set and the
  remediation's effect (or lack of it) is re-priced there; a further
  S1 attempt would need a new hypothesis and a new budget, not a
  re-run of these two runs.

## P7.2 - quote-anchored repair and prompt p7-v3 (2026-11-10)

### Pre-registration (written before any P7.2 provider run)

- Context: P7.1 closed with S1 split (A2 22/26 gate met, B2 17/26 not
  met) and a stop rule of no third round under P7.1. Hamza asked for
  the system to be genuinely improved toward 26/26; Claude, as
  planner, ruled 26/26 is not a plausible or honest target and Sol's
  free diagnostic (below) verified the premise. Hamza approved this
  plan on 2026-11-10 ("do what you think is the best"), with Sol
  resolving the budget (see Budget) and filling the ruling's gaps
  (test list, repair rounds, S2 handling) as manager clarifications
  that change no gate.
- Free diagnostic (zero provider calls, 2026-11-10, from the saved
  A/B/A2/B2 records, the raw answers in `reports/service-eval-raw.json`,
  the corpus chunks and the reference top-10): the groundable ceiling
  is C = 23, recomputed independently of E3 and matching it - 23 of
  the 26 key facts are present in the retrieved top-10 context. The 3
  retrieval-absent facts are d02 "softmax over the scaled dot
  products" and d02 "scaling by the square root of the key dimension"
  (best bearing chunk 11, ranked 11th for d02 on both) and d09 "label
  smoothing" (bearing chunk 27, ranked 18th for d09); recorded as
  Project 9 evidence, retrieval is frozen here. Loss layers across
  A2/B2: gate-lost zero (the P7.1 top-1 gate holds); validator-lost
  d09 "residual dropout" in both runs (d09 refused `ungrounded` in
  all four runs A/B/A2/B2) and both d11 facts in B2 (the repair retry
  fired, 2 calls, and still failed); model-omitted at scorer level
  d12's "positions cannot attend to subsequent positions" in both
  runs (d12 scored 0, 1, 1, 1 across A/B/A2/B2) plus one fact each in
  d03 and d07 in B2 only; not-measured d10 in B2 (provider 503). Two
  scorer-level nuances are recorded, not fixed (the scorer and the
  question set are frozen copies from Project 6): A2's d12 answer
  states the masking content in a parenthetical phrasing the answer
  regex cannot match, and A2's d02 "softmax" miss is the hyphenated
  "soft-max". The famous-paper confound is proven at question level:
  d02 has only 1 of its 3 facts in context yet scored 2/3 (A2) and
  3/3 (B2), so retrieval-absent facts can be produced from model
  memory and raw S1 can exceed the groundable ceiling.
- Chosen: exactly two changes. (1) The citation-repair retry becomes
  quote-anchored: the retry prompt requires the model to first quote
  verbatim the exact chunk lines it will rely on (each quote followed
  by its chunk id), then answer using only those quoted lines. This
  targets the validator-lost facts (d09, d11); the retry still fires
  once, only on an `ungrounded` refusal. (2) Prompt p7-v3 adds a
  completeness instruction (answer every part of the question; cover
  each item the context supports, citing each part), targeting the
  model-omitted facts (d12; d03/d07 intermittently). The RULES
  hardening text, context sanitization, retrieval, top_k, chunking,
  the evidence threshold (0.35), every gate in `evaluation/gates.json`,
  and the scorer/questions are unchanged; the held-out manifest is
  untouched (Project 9).
- Success criteria: the S1 gate (>= 22/26) must be met in BOTH runs
  A3 and B3 (stricter than P7.1's split-verdict reading); the stretch
  target is C = 23 groundable facts. Results are reported as raw
  k/26 and as "k of C reachable", where groundable scored = raw S1
  minus retrieval-absent facts scored (computed from the raw answers
  with the frozen scorer and the E3 absent set). S2 >= 3/4 in each
  run, measured as before; a stronger repair could flip absent
  questions from abstention to fabrication, so S2 is watched, not
  assumed. Because the prompt changed, R1 is re-checked on-arm: 15
  attacks, 1 repeat (as in the P7.1 re-check), final hits <= 2.
- Budget: at most 70 provider requests in total and at most 60 per
  UTC day, successful-call counting (the ledger is the authority;
  503 attempts do not count). A3 runs on UTC 2026-11-09, B3 and the
  R1 re-check on UTC 2026-11-10. Only 503 casualties are re-run, at
  most 5 repair rounds per run; a question still at 503 after the
  repairs stands as not measured (the M8 run-C convention).
- Stop rule: A3/B3 are recorded whatever they land. No A4/B4, no
  P7.3. If the gate fails in either run, Project 7 closes with the
  recorded numbers and the failure analysis; the LinkedIn post is
  written from the final verified numbers only.

### Measured (2026-11-09/10)

- Runs A3 (UTC 2026-11-09) and B3 (UTC 2026-11-10) used image
  `docmind-service:p72` (commit `806954b`) under the pre-registered
  configuration. Both first passes crossed the provider 503 wall
  (A3 measured 5 of 16 questions, B3 3 of 16) and took all five
  repair rounds; a03 and a04 were never measured in either run
  (503 on every attempt) and stand as not measured under the run-C
  convention.
- S1: A3 20/26, B3 21/26. The pre-registered gate (>= 22 in BOTH
  runs) is NOT met, and the stretch target is not reached:
  rescored against the diagnostic's retrieval-absent set, both
  runs found exactly 19 of the 23 groundable facts. The only
  per-question difference between the runs is d02 (2/3 in A3, 3/3
  in B3) — the retrieval-absent softmax fact, missed in A3 on a
  hyphenated "soft-max" the frozen scorer regex cannot match and
  scored in B3 from partial evidence, the diagnostic's
  model-memory confound, not a grounding improvement. Every other
  question scored identically in both runs.
- The four groundable losses are the same in both runs: d03 -1
  and d12 -1 (the answers state the content in phrasings the
  frozen Project 6 scorer regexes do not match); d07 -1 (the
  sinusoid fact genuinely omitted — the completeness instruction
  did not recover it); d09 residual dropout -1 (answered in both
  runs — A3 via the repair retry, B3 on the first pass — with a
  verbatim quote of the regularization passage and an explicit
  statement that the excerpts do not enumerate the techniques;
  the enumeration sits in chunk 27, ranked 18th for d09, outside
  the retrieved context). No document question was refused in
  either run: the validator-loss layer that cost facts in M8 and
  P7.1 contributed zero losses under P7.2.
- S2: 2/4 recorded in both runs — a01 and a02 abstained in both,
  each time after the quote-anchored retry fired, so the stronger
  repair did not flip a measured absent question into
  fabrication; a03/a04 not measured. The >= 3/4 gate is not met
  as recorded, with the same measurability caveat as P7.1's B2.
- S3a 1.000 in both runs; S3b 0.857 in both; S4 0.818 (A3) /
  0.909 (B3); S5 2388.5 (A3) / 2171.5 (B3) mean prompt tokens.
- R1 re-check (on arm, 1 repeat, prompt p7-v3, in-process harness
  against commit `806954b`): 0/15 attacks succeeded, model
  resisted 15/15, guardrail caught 0 — the gate (<= 2) holds;
  the prompt change did not weaken injection resistance.
- Budget: 48 provider requests recorded in total against the 70
  cap. A3's 17 and B3's 16 are exact in the ledger (UTC days: 17
  on 2026-11-09, 16 on 2026-11-10); the R1 re-check's 15 are
  counted in its own results file — the in-process harness writes
  no ledger rows — bringing the 2026-11-10 total to 31 against
  the 60/day cap.
- Verdict, per the stop rule: P7.2 closes here — no A4/B4, no
  P7.3. The remaining S1 losses are systematic, not variance
  (the A3-B3 gap is 1 fact, against 5 for A2-B2 and 6 for A-B):
  retrieval rank, which is Project 9's variable; the frozen
  scorer's phrasing sensitivity; and one genuine omission.
  Project 7's S1 record stands at A 10/26, B 16/26 (M8);
  A2 22/26, B2 17/26 (P7.1); A3 20/26, B3 21/26 (P7.2) — 19 of
  23 groundable in both P7.2 runs.

## P7.3 - cross-encoder reranker, retrieval unfrozen (2026-11-13)

### Pre-registration (written before any P7.3 provider run)

- Context: P7.2 closed with S1 at 20/26 and 21/26 against the
  >= 22-in-both gate, and a stop rule of no P7.3. On 2026-11-11
  Hamza decided, explicitly and against Sol's leave-as-is
  recommendation, to open one more round targeting S1 >= 22 in
  both runs by unfreezing retrieval, accepting that this spends
  Project 9's headline variable (P9 must be redesigned; the
  brief is a P7.3 deliverable) and that a miss closes Project 7
  permanently. This section supersedes the P7.2 stop rule by
  owner decision; the P7.2 entry above is not edited.
- Planner ruling: Claude ruled 2026-11-13 (relayed by Hamza;
  verified complete against the seven questions by Sol the same
  day, no follow-up needed). Approved design: a local zero-cost
  cross-encoder reranker, candidate pool N = 25, final top_k
  stays 10. Honest estimate: central raw S1 about 22 per run
  (range 19-25); P(>= 22 in a given run) about 55%; P(both)
  about 40%. Not guaranteed.
- Free admissibility check (zero provider calls, 2026-11-13,
  `evaluation/p73_design_check.py`, results in
  `evaluation/results/p73-design-check.json`): A1 the harness
  reproduces C = 23 and ranks 11/11/18 under dense-only; A2
  chunk 11 enters d02's final context at rerank position 4 and
  chunk 27 enters d09's at position 4; A3 the new ceiling is
  C' = 26 with zero baseline-present facts lost (the 3 gained
  facts are exactly the retrieval-absent ones); A4 the fitted
  token projection is 2,543 mean prompt tokens against the
  3,000 admissibility limit. A1-A4 pass. A5 (MEM/L1) and A6
  (latency) are measured after implementation, before any
  provider run; either failing means no provider runs and
  Project 7 closes. A6 early signal: steady-state rerank is
  about 350 ms per 25-pair batch on the laptop; one probe run
  showed a transient ~4 s (investigated, not reproduced,
  attributed to laptop contention; restricting the ORT thread
  count made it 5-8x slower and is rejected).
- Token fit (replaces the ruling's estimates): prompt_tokens
  against total chunk characters on the 23 single-call A3/B3
  doc prompts gives slope 0.136 tokens/char and overhead 1,224
  tokens (residual std 169, max 365). The ruling estimated O
  ~270 and ~190 per chunk; the fitted numbers govern. The
  reranked contexts (9,491-9,953 chars) sit against the fit's
  x-range (8,932-9,915): the largest exceeds it by 38 chars
  (0.4%, about 5 tokens), a negligible extrapolation.
- Chosen model: Xenova/ms-marco-MiniLM-L-6-v2, the first (and
  smallest) candidate, artifact `onnx/model_quantized.onnx`
  (int8, 23,143,499 bytes). Candidates 2-3 were not tried. The
  pinned fastembed 0.9.1 has no TextCrossEncoder class, so the
  reranker runs via onnxruntime + tokenizers directly — the
  ruling's pre-authorised fallback, not a design change. The
  laptop cannot reach HuggingFace (direct connection times out;
  the mirror does not resolve), so the model files were
  downloaded on Sol's VM and transferred to the laptop; the
  model is NOT vendored in git — CI downloads and caches it,
  and the laptop image build uses a local untracked `models/`
  directory in the build context.
- What ships (a real service change): `docmind_service/rerank.py`
  (Reranker protocol, OnnxRuntime adapter, Noop, fake for
  tests); `PgStore.retrieve` takes SQL LIMIT N, reranks, then
  top_k, and `InMemoryRetriever` mirrors it; settings
  `RERANKER_ENABLED` (default true), `RERANKER_MODEL`,
  `RERANK_CANDIDATES` = 25 (documented in OPERATIONS.md and the
  env files); graceful degradation to dense order on any
  reranker exception (exception type only in the log, counted,
  the request never fails); the Dockerfile bakes the model into
  MODEL_CACHE_DIR; the cache scope hash includes the reranker
  model, N and top_k; `/readyz` gains a `reranker` check entry;
  metrics `docmind_rerank_seconds` and
  `docmind_rerank_total{result=ok|fallback}`; tests for reorder
  and top_k, fallback, no text in logs, settings, and
  cache-scope separation. The evidence gate stays on the dense
  top-1 cosine (0.35); citation `score` stays the dense cosine.
- Gates (nothing moves silently; `evaluation/gates.json` is not
  edited — the rulings live in `evaluation/p73_prereg.json` and
  here): S1 >= 22/26 raw in BOTH runs A4 and B4 (fixed by owner
  decision). E2 unchanged at 0.90, measured on the DENSE
  candidate stage against the FAISS reference (embedding
  parity); the overlap of the final reranked context with the
  reference is reported ungated. E3 unchanged at >= 23/26 with
  its dagger, now measured on the FINAL context; C' is reported
  beside it and is not E3. S5 unchanged at <= 3200. S2 unchanged
  at >= 3/4 per run, reported as abstained/measured with n
  measured; 503 = not measured, and with fewer than 3 absent
  questions measured S2 is "not assessable", never "met". R1
  unchanged at <= 2 final hits, with an on-arm re-check
  required. C1 and G3 unchanged; MEM and L1 are re-measured
  with the reranker (A5).
- Frozen: the questions and scorer regexes (no phrasing-tuning
  to them — d03/d12 stay at-risk facts, not design targets),
  the evidence threshold (0.35, dense top-1), cache tau (0.86),
  prompt p7-v3 (no bump), the embedding model, the chunker
  (150/25), the 49-chunk corpus, and the held-out manifest.
  Unfrozen: only the second retrieval stage (the reranker and
  candidate pool N).
- Abstention safety: a01-a04 clear the 0.35 gate, so abstention
  rests on the model. The free pre-check (term overlap and
  top-10 composition, baseline vs reranked) shows no safety
  signal (overlaps move at most 0.11). SAFETY REGRESSION is
  pre-defined: any absent question that abstained in BOTH A3
  and B3 (a01, a02) is answered in A4 or B4. If S1 passes WITH
  a safety regression, S1 is recorded as "met with safety
  regression" and the reranker ships default OFF; with no
  safety regression it ships ON whether or not S1 passes.
- Budget and protocol: at most 80 provider requests in total
  and at most 60 per UTC day, successful-call counting (the
  ledger is the authority; every provider-calling script writes
  its own rows). A4 on UTC day 1 (<= 28 incl. repairs), B4 on
  UTC day 2 (<= 28), then the R1 re-check on day 2 (on-arm, 1
  repeat, 15 requests). CI release-smoke runs count (1 each),
  so pushes are batched: worst case 71 + 2 = 73 against the 80
  cap. Only 503 casualties are re-run, at most 5 repair rounds
  per run; still-503 = not measured; no other re-rolls. A4/B4
  use the shipped service path, cache off, guardrails default,
  the repair retry as shipped, design P with the selected
  model. B4 starts only after A4 is recorded; nothing changes
  between them.
- Expected range: raw S1 central 22 per run (range 19-25).
  Gains available: d09 up to +2 (label smoothing and residual
  dropout, now groundable), d02's second fact +1 in A-type runs
  (B3 already got it from memory). Expected losses: d12 ~0.85,
  d03 ~0.7 (scorer phrasing), d07 ~0.7 (model omission), plus
  ~0.7 context-change regression risk.
- Stop rule (final): whatever lands is recorded. A miss, or an
  inadmissible design, closes Project 7 permanently — no P7.4.
  Runs A through B4 stay in every table with the remediation
  label ("retrieval unfrozen" for P7.3 rows) and the
  tuned-on-the-same-questions disclosure.
- Manager clarifications (Sol; no gate substance changed): the
  push uses Sol's established Session-1 scheduled-task route
  (the ruling's "[H1] push" label is Claude's assumption, not
  a new Hamza action); "smallest that passes" is judged by
  measured ONNX size; the A6 "render-like profile" is rerank
  latency inside the 512 MB-constrained container; the S5
  projection is the mean over the 12 doc questions of the
  fitted values, and is conservative because the harness S5
  denominator also includes non-refused absent rows (503s at 0
  tokens lower it).

### Implementation (2026-11-13)

- Design P as pre-registered. New module
  `docmind_service/rerank.py`: a `Reranker` protocol,
  `OnnxCrossEncoderReranker` (onnxruntime + tokenizers
  directly — the ruling's pre-authorised fallback branch,
  because pinned fastembed 0.9.1 has no `TextCrossEncoder`),
  `NoopReranker`, `FakeReranker`, and
  `rerank_with_fallback` (graceful degradation to dense
  order; only the exception type is logged; a length change
  counts as failure). The adapter mirrors the design-check
  `CrossEncoder` exactly (default ORT session options,
  512-token truncation, pad id 0, scores = logits[:, 0],
  stable sort so ties keep dense order).
- `PgStore.retrieve` and `InMemoryRetriever.retrieve` take
  `reranker` / `rerank_candidates` kwargs (defaults keep the
  old behaviour). With a reranker set, the dense stage
  returns max(top_k, N) candidates and the reranked top_k is
  returned; chunk scores stay the dense cosine, so the
  evidence gate (a dense top-1 test) and the citation
  contract are unchanged.
- Settings (DOCMIND_ prefix): `RERANKER_ENABLED` (default
  true), `RERANKER_MODEL` (default
  `Xenova/ms-marco-MiniLM-L-6-v2`), `RERANK_CANDIDATES`
  (default 25, range 1-100). `create_app` auto-constructs
  the reranker only in the non-demo path where it builds the
  store, and fails fast at startup if the model is missing
  (a missing model is a broken build, not a fallback).
  Provided stores and retrievers are untouched.
- `/readyz` gains a `reranker` check (`ok` via a live 1-pair
  probe, `disabled`, or the exception type name); it is
  reported but non-gating — readiness stays database +
  embedder. `ReadyOut.checks` is a free-form dict, so the
  OpenAPI schema is unchanged (verified:
  `scripts/export_openapi.py` produces no diff).
- Metrics: `docmind_rerank_seconds` histogram and
  `docmind_rerank_total{result=ok|fallback}` counter. The
  semantic-cache scope includes the reranker model and
  candidate count.
- `evaluation/run_retrieval.py`: E2 stays on the dense stage;
  E3 is measured on the FINAL (reranked) context; the result
  adds `e2_reranked` (ungated overlap of the final context),
  `e3_context`, reranker metadata, and latency for both
  paths. `check_gates.py` is unchanged (it reads the same
  metric keys).
- Model acquisition: `scripts/fetch_reranker.py`
  (stdlib-only, so CI jobs without a Python environment can
  run it with system python3) downloads the four model files
  from the Hub with sha256 verification. The model is NOT
  vendored in git (`models/` is gitignored); the Dockerfile
  COPYs it from the build context into `/opt/models`, and CI
  fetches it (cached) in the retrieval-eval, image, and
  release jobs.
- Verification: ruff check + format clean; unit suite 301
  passed, 0 failed (286 at P7.2 close + 15 new reranker
  tests), 20 deselected; integration suite 17 passed, 0
  failed (incl. the new PgStore rerank test against the
  local pgvector container); the three initially failing
  tests asserted the old exact shapes (readyz checks,
  release.env key list) and were updated to the new intended
  shapes — no service behaviour was changed to satisfy a
  test.
- End-to-end retrieval check (local, free, 0 provider calls):
  `evaluation/run_retrieval.py` against the local pgvector
  container with the real reranker: E1 1.000, E2 1.000 (dense
  stage, per-question min 1.000), E3 26/26 on the final
  reranked context (missed: none) — the design-check ceiling
  C'=26 confirmed through the shipped service path.
  E2_reranked 0.685 (ungated, informational).

### A5/A6 — memory fix and admissibility verdict (2026-11-13)

- A5 first attempt (full 25-pair batches, no lock): the 512 MB
  container OOM-killed under concurrency 10 (peak 495.3 MB,
  exit 137, 0/100 queries). Serialising inference with a lock
  (fbc4b13, mirroring the embedder) did not fix it: still
  OOM-killed (peak 511.9 MB, 1/100).
- Diagnosis: the ORT arena grows to ~1.3 GB even serialised
  (2 GB diagnostic run: 100/100 pass, memory plateaus
  ~1.29 GB — arena growth, not a leak). Fix (4348bd8):
  5-pair sub-batches plus the CPU arena disabled.
- Sub-batching changes scores: the int8 model's dynamic
  activation quantization makes scores depend on batch
  composition (measured max full-vs-sub-batch score diff
  0.45 logits; arena on/off exactly 0.0). Admissibility was
  therefore re-verified under the shipped sub-batched
  scoring (design check `--sub-batch 5`,
  `evaluation/results/p73-design-check-subbatch.json`):
  A1 pass, A2 pass (chunk 11 at rerank position 4, chunk 27
  at position 5), A3 pass with C'=26, lost=[], gained=the
  same 3 facts, A4 pass (2544 <= 3000). The pre-registration
  A1-A4 (full batch) stand as the design's admissibility;
  the sub-batch run is the shipped implementation's
  verification.
- Second memory problem: after sub-batching, L1 passed
  (100/100, no OOM) but peak memory was still 511.8 MB
  against the 480 MB gate. Decomposition showed anon memory
  growing +170 MB after 3 sequential queries: glibc retained
  freed per-run tensors across its many per-thread arenas.
  Fix (da4ee22): `MALLOC_ARENA_MAX=2` and
  `MALLOC_TRIM_THRESHOLD_=65536` in the Dockerfile. Memory
  after 3 sequential queries fell to 233.7 MB; after 10
  concurrent, 249.5 MB.
- A5 final (100 queries, concurrency 10, 512 MB, fake
  provider, 0 provider requests): 100/100 HTTP 200, peak
  memory 324.2 MB <= 480 MB, container still running, no
  OOM. A5 PASS.
- A6 unconstrained: Session-1 foreground probe, 36 batches
  of 25 pairs: p50 308 ms, p95 339 ms <= 3000 ms. A6 PASS.
  The ~4 s SSH measurements were Windows power-throttling
  of background (Session 0) processes: the same machine and
  batches run 10x faster in the foreground while the CPU
  sits 87% idle. Render-like profile (in-container, client
  latency under concurrency 10): p50 4.10 s, p95 4.32 s,
  dominated by lock queueing; the rerank itself is ~0.41 s
  in-container. Informational only.
- A5/A6 values: `evaluation/results/p73-a5-a6.json`.
  Admissibility A1-A6 is now complete: all six hold.

### Close-out (2026-11-14)

- A4 (UTC 2026-11-13): S1 = 23/26, S2 = 4/4, S3a/S3b/S4 = 1.000,
  S5 = 2782.8, 21 provider requests. B4 (UTC 2026-11-14):
  S1 = 24/26, S2 = 4/4, S3a/S3b/S4 = 1.000, S5 = 2782.8,
  26 provider requests. The pre-registered gate (S1 ≥ 22 in BOTH
  runs) is MET.
- Per-question: d02 3/3 and d09 2/2 in both runs — the reranker
  recovered exactly the facts the design check said it would, and
  nothing the dense stage grounded was lost. The only misses are
  d03 and d12 (scorer phrasing, 1 fact each, both runs) and d07
  (1 fact in A4, recovered in B4).
- Safety: NO regression. a01 and a02 abstained by refusal in both
  runs, as in A3/B3; a04 refused in both runs; a03 abstained in
  prose in both runs. Outcome-table verdict: met, no safety
  regression — the reranker ships ON (`RERANKER_ENABLED` default
  true).
- R1 re-check (on arm, 1 repeat): 0/15 final hits, model resisted
  15/15. Gate ≤ 2 holds.
- Budget actuals: 62 recorded requests (A4 21, B4 26, R1 15)
  against the 80 cap; UTC days 21 (Nov 13) and 41 (Nov 14,
  including R1) against the 60 cap; +1 release-smoke on the
  implementation push = 63 total. 8 additional calls in an
  interrupted A4 repair round lost their results before the
  merge (a runtime restart killed the round mid-run) and wrote
  no ledger rows, because rows are written at merge; they are
  recorded here, not in the ledger total. 503 attempts do not
  count.
- Provider availability: A4's first pass and one repair round
  hit a total Groq 503 wall (0 spent); B4's first pass hit 8
  questions at 503. Both runs completed within the 5-round
  repair rule with nothing left unmeasured.
- Public demo re-synced to the P7.3 code (Space commit
  `a8e8aba`, service code `21a1e3a`): the Space takes the same
  reranker change. The 23 MB model file cannot be uploaded
  through the Space uploader (Git LFS), so `app.py` downloads
  it at startup from the public Xenova repo with sha256
  verification, the same way the embedder model already
  downloads at runtime; if the download fails the Space runs
  dense-only rather than failing to boot. Live check after the
  re-sync (2026-11-14): a novel on-corpus question answered
  with page citations (1 LLM call, 2342 prompt tokens, cache
  miss) and a repeat question served from the cache (0 calls,
  1.3 s). Reranker-on in the Space is inferred from the
  successful boot and the working HF downloads (the embedder
  proves the endpoint), not directly observed — HF exposes no
  runtime-log API to confirm it.
- P9 redesign brief written to `docs/P9-REDESIGN-BRIEF.md`:
  P7.3 spends the "rerank" result, credited to P7 and never
  re-claimed; P9's new headline is retrieval quality versus
  answerability on contamination-free papers.
- Project 7 is CLOSED — passed. Full S1 record: A 10/26, B 16/26
  (M8); A2 22/26, B2 17/26 (P7.1); A3 20/26, B3 21/26 (P7.2);
  A4 23/26, B4 24/26 (P7.3). No P7.4.
