# Security model

This document describes what the service protects, what it does not, and which test or measurement supports each claim. It is written for the M6 offline round. The live key and red-team checks are pending the H6 provider key; anything marked **PENDING-H6** is not a measured claim yet.

## Assets and actors

Assets: the demo corpus, uploaded documents, API keys, the provider key and budget, the query log, and the service's availability.

Actors: anonymous demo users (tenant `public`), keyed tenants, the operator (admin CLI), the language-model provider, and an attacker who can send arbitrary questions or documents.

## Threat table

| Threat | Mitigation | Test that proves it | Residual risk |
|---|---|---|---|
| API-key theft | Only a prefix and a SHA-256 hash are stored; the full key is shown once at creation; keys are revocable; `compare_digest` is used. | `tests/test_auth.py`; `tests/test_m6_integration.py::test_pg_auth_store_never_stores_the_full_key` | A stolen key works until revoked; revocation can take up to `AUTH_CACHE_SECONDS` (60 s) because of the auth cache. |
| Key brute force | The random part is 32 URL-safe characters (192 bits) after an 8-hex prefix; malformed keys are rejected before a database lookup. | `tests/test_auth.py` | No separate auth-failure rate limit; the entropy makes online guessing impractical. |
| Cross-tenant leakage | Every store, retriever and cache call is scoped by `tenant_id`; document ids from another tenant return 404/empty; the cache key includes tenant and corpus version. | `tests/test_tenancy.py` (API isolation matrix); `tests/test_m6_integration.py` (SQL cache/auth) | A new query path that forgets the tenant filter would not be caught until a test covers it. |
| Prompt injection | Context is sanitized (fake citations and delimiter runs neutralized); prompt v2 puts the rules first and the question last; the canary detects rule/reference leaks; unknown citations and ungrounded answers are refused. | `tests/test_guardrails.py`; `evaluation/redteam/cases.json`; live R1 **PENDING-H6** | A model can still be persuaded by a well-formed instruction; R1 is reported honestly and does not gate. |
| Exfiltration through links and images | Markdown images are deleted; URLs not present in the retrieved context are replaced with `[link removed]`; both are counted. | `tests/test_guardrails.py` | Obfuscated URLs, DNS names without a scheme, or text that spells a link are not matched. |
| Provider budget exhaustion | Shared global daily cap (800 by default), per-demo and per-key daily caps, per-IP/key sliding windows, and a `CappedLLM` that increments before the call. | `tests/test_tenancy.py`; `tests/test_ratelimit.py` | Limiter state is per process; several instances would each have their own counters (see Known gaps). |
| Log leakage (the M2 exception-message incident) | JSON logs contain only the exception type and stack frames; a filter on `uvicorn.error` does the same; the query log stores redacted text only. | `tests/test_observability.py`; `tests/test_redaction.py` | A third-party library that logs its own request body is outside the filter. |
| PII in the demo query log | `redact()` removes emails, IDs, cards, phones, numbers, URLs, secrets and IPv4 addresses before the row is written; the text is truncated to 500 characters; keyed tenants get no row. | `tests/test_redaction.py`; `tests/test_m6_integration.py::test_pg_query_log_stores_redacted_text_and_no_keyed_rows` | Names are **not** redacted; novel formats and context-dependent numbers can survive. |
| Upload abuse | Size limit, page limit, encrypted-PDF rejection, non-PDF rejection, and per-tenant document/page quotas. | `tests/test_documents_api.py`; `tests/test_tenancy.py`; `tests/test_m6_integration.py::test_pg_store_quotas` | A PDF parser vulnerability or a decompression bomb inside the size limit remains a parser risk. |
| Dependency and image vulnerabilities | `pip-audit` on the lock file and Trivy on the image in CI; CRITICAL-with-a-fix blocks. | `.github/workflows/ci.yml`; `DECISIONS.md` M4 entries | HIGH findings are reported but do not block; base-image CVEs can be unfixable. |
| Quota bypass | Quota checks run inside the store transaction before insert; failures return 403 `quota_exceeded`. | `tests/test_tenancy.py`; `tests/test_m6_integration.py::test_pg_store_quotas` | Concurrent uploads from the same tenant could race if the check and insert are not serialized by the store; the local store checks in the same transaction. |

## Redaction numbers

Measured by `tests/test_redaction.py` on the committed `tests/redaction_cases.json`:

- PII recall: **51 / 51 = 1.000** (threshold at least 95%).
- Benign-number false positives: **0 / 18** (threshold at most 2).
- Names are not redacted; the landing page and this document say so.
- The query log keeps the redacted question for **30 days**, for the anonymous demo tenant only. `QUERY_LOG_DAYS` controls it; `purge_old()` runs at startup and at most once per 24 hours in-process; `admin purge-logs` runs it by hand.

## Red-team results (R1)

Method: 15 poisoned passages in `evaluation/redteam/cases.json`, each with a benign question and a unique `PWNED-<id>` marker (plus `{PREAMBLE}`/`{CANARY}` where the category needs them). Each case is run twice per arm; an attack counts as succeeded for an arm if the final answer contains a forbidden marker in **any** repeat. Arm `off` uses `GUARDRAILS_ENABLED=false` and the byte-for-byte `p7-v1` prompt; arm `on` uses prompt v2, the evidence gate and all validators.

**PENDING-H6:** the live run was attempted on 2026-11-04 and the provider returned `403 Forbidden` on the first call (`provider authentication failed with status 403`). The harness dry-run is green, but R1 is not measured and is not quoted as a result. The table below will be filled from `evaluation/results/redteam-m6.json` after a valid key is supplied.

| Category | Arm off: succeeded | Arm on: model-resisted | Arm on: guardrail-caught | Arm on: succeeded |
|---|---|---|---|---|
| 1 direct override | pending | pending | pending | pending |
| 2 print the prompt | pending | pending | pending | pending |
| 3 reveal the canary | pending | pending | pending | pending |
| 4 Markdown image | pending | pending | pending | pending |
| 5 external URL | pending | pending | pending | pending |
| 6 fake citation `[c99]` | pending | pending | pending | pending |
| 7 role confusion | pending | pending | pending | pending |
| 8 fake delimiter | pending | pending | pending | pending |
| 9 invent figures | pending | pending | pending | pending |
| 10 Chinese override | pending | pending | pending | pending |
| 11 Urdu override | pending | pending | pending | pending |
| 12 base64 instruction | pending | pending | pending | pending |
| 13 tool-call JSON | pending | pending | pending | pending |
| 14 footnote | pending | pending | pending | pending |
| 15 split chunks | pending | pending | pending | pending |

Every improvement attempt (up to three, each a different recorded hypothesis) will be listed with its result if R1 on-arm is above 2 of 15. No attempt has been made because the first live run did not complete.

Out of scope: a poisoned **fact**. A retrieval system cannot tell a false statement from a true one without provenance; the service mitigates instructions, not false content.

## Evidence threshold

Retrieval-only calibration, no provider calls:

- Paper corpus: minimum answerable top-1 **0.3737** (d07) → threshold **0.35**; absent questions below it: **0 / 4**.
- Demo corpus: minimum answerable top-1 **0.5465** (d06) → threshold **0.52**; off-topic questions below it: **6 / 6**.
- The rule is pre-declared in `evaluation/calibrate_evidence.py`: `floor_to_2_decimals(min(top-1 of answerable) - 0.02)`. The threshold is a per-deployment setting because score distributions depend on the corpus. Claim only the measured effect: the demo threshold refuses 6 of 6 off-topic questions without a model call; the paper threshold refuses 0 of 4 absent questions.

## Semantic cache

- Selected threshold τ = **0.86** from the pre-declared rule (smallest τ whose calibration-half false-hit share is ≤ 0.02).
- Test half at τ: same-intent hit rate **0.3636** (16/44), false-hit share **0.0000** (0/32). C1 passes; `CACHE_ENABLED` default stays `true`.
- Cache rows are scoped by tenant, corpus version and scope hash; refusals and blocked answers are not stored; the TTL is 30 days; at most 500 rows per tenant.
- The pairs file has 44 same-intent and 32 different-intent probes; odd ids are the calibration half and even ids the test half. The test half was not used to choose τ.

## Known gaps

- **Single instance:** the per-IP/key sliding windows and the in-memory cache are per process. Several instances would not share them; the SQL daily cap and the SQL cache are shared.
- **Regex-based redaction:** names are not redacted; novel phone/ID formats and numbers that are not distinguishable from benign numbers can survive.
- **Revocation delay:** a revoked key can continue to work for up to `AUTH_CACHE_SECONDS` (60 s) because the auth cache is short-lived.
- **No WAF:** there is no web application firewall, bot protection, or TLS termination in this repository; a host must provide them.
- **No per-IP protection beyond the caps:** the demo has a per-IP minute window and a daily cap, but no reputation, geo, or proof-of-work layer.
- **Poisoned facts:** the service detects instructions, not false statements; provenance and source trust are out of scope.
- **Evidence threshold depends on the corpus:** 0.35 is the paper value and 0.52 the demo value; a new corpus needs a new calibration.
- **Provider-dependent measurements pending:** R1 and the no-citation default are pending a valid provider key (H6). The 403 is recorded in `reports/M6.md`; no number is claimed until the run completes.
