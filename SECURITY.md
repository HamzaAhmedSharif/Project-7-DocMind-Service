# Security policy

## Reporting a vulnerability

Use GitHub private vulnerability reporting: **Security → Report a vulnerability** on
https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service
(enabled under `[H5]`). If the form is unavailable, open a public issue that says only
"security report, please contact me privately" and wait for an invitation to a private
channel. Do not include secrets, keys, tokens, connection strings or exploit details in
a public issue, and never paste them into a chat or into this repository.

## Supported versions

`main` only. The service is pre-1.0 and deployed from `main`; older commits and the
evidence branches are not maintained.

## What to expect

Best-effort response. This is a portfolio project, not a commercial service: expect an
acknowledgement within a few days and a fix or an explanation in the next milestone
window. No bounty is offered.

## Scope

What the service stores and processes:

- Uploaded PDFs: text is extracted, chunked and stored in Postgres/pgvector; the PDF bytes
  are not kept. Every upload gets a `sha256` and a per-tenant row.
- Questions, answers, citations, token usage and latency are logged as **counts and IDs
  only** — question and answer text are never written to logs (see `DECISIONS.md`).
- The service ships with a fake LLM provider by default; a real provider key
  (`DOCMIND_LLM_API_KEY`) is read from the environment and never stored or logged.
- The public deployment (M5) is rate-limited and read-only; uploads are disabled there.

Out of scope: vulnerabilities in upstream dependencies (report them upstream, but tell
us if our pin is affected), and attacks that require a valid hosting credential.
