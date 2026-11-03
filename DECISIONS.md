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

### Post-hoc threshold change: E3
- Gate and original threshold: E3, `e3_key_facts_found >= 24` of 26 (gating).
- Measured value (source file, commit): 23/26 in `evaluation/results/retrieval-m3.json`.
- Fix attempts (three, each a different hypothesis, each with its result):
  1. Chunk count vs P6: 49 chunks, matches P6 exactly (PASS — not the cause).
  2. E1 cosine vs reference vectors: 1.0 min / 1.0 mean (PASS — embedding parity confirmed).
  3. E2 top-10 overlap vs FAISS reference: 1.000 mean (PASS — retrieval matches P6 exactly).
- New threshold and the rule that sets it: threshold stays at 24/26; no change. The miss is inherent to the question set: the d02 softmax/scaling key facts and one d09 fact are not in the top-10 chunks retrieved by the same method P6 uses. Marked with † in `reports/M3.md`.
- Would revisit if: M8 changes the question set, chunking, or top-K.

