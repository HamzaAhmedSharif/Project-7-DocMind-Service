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
