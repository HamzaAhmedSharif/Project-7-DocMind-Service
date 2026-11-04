# Operations (M5 / M7 skeleton)

## Hosting options evaluated (all read on 2026-11-04)

| Host | What the sources say | Verdict |
|---|---|---|
| Render | Demanded a card at signup (Sol, 2026-11-04); an independent test also reports a card (with a small hold) is needed to deploy a web service | **OUT** (trigger fired) |
| Koyeb | Pricing FAQ: a card is required "to prevent fraud and abuse", verified by a $29 pre-authorization hold; acquired by Mistral AI in February 2026; new accounts start on a paid plan | **OUT** |
| Hugging Face Docker Space | Hub docs: "Gradio and Docker Spaces run on compute and require a paid plan to create"; only static Spaces are free (forum thread of July 2026: Docker SDK marked Paid) | **OUT, confirmed** |
| Hugging Face Gradio Space on free ZeroGPU (2 per free account; Project 6 uses one) | Technically able to start an ASGI app, so "presumed out" is not strictly true. Refuted for this project for three reasons: it is not the container we gate (a Gradio wrapper and a requirements install replace the audited image), ZeroGPU demands a GPU-decorated function so a CPU API would need a no-op one (a workaround third parties document, against the purpose of the allotment and a policy risk), and it would take the second and last free slot | **OUT (refuted: possible, but distorts the artifact and the platform's terms)** |
| Northflank Sandbox | Pricing page: "Free, No card needed, always on, 2 services, up to $20/mo of resources". Billing docs: "all users must add a payment method to start creating resources on Northflank, regardless of plan selection". Railway's comparison page and two directories also say a card is required. The primary sources disagree; the docs are explicit and recent | **PROBE (bounded, A1.6); presumed out until it passes** |
| SnapDeploy | Only vendor pages: no card, 512 MB and 0.25 vCPU per container, 100 hours per month, auto-sleep with a wake of about a minute. The same vendor's blogs listed Render as card-free, which today's signup disproved, so its claims are unverified | **PROBE (bounded, A1.6); lowest confidence** |
| Fly.io, Railway, Google Cloud Run, Oracle | Card or billing account (Sol 2026-11-04; earlier research of 2026-10-27) | **OUT** |

Evidence log: `northflank.com/docs/v1/application/billing/project-types`, `northflank.com/pricing`, `docs.railway.com/platform/compare-to-northflank`, `koyeb.com/docs/faqs/pricing`, `huggingface.co/docs/hub/en/spaces-overview`, the Hugging Face forum thread "Docker SDK now marked as Paid" (July 2026), `snapdeploy.dev` (vendor pages).

## How to run the release image

The release image is `ghcr.io/hamzaahmedsharif/docmind-service:sha-<7-char-commit>`. It carries its commit in `DOCMIND_GIT_SHA`, set at build time with `--build-arg GIT_SHA=<commit>`, and the revision in the `org.opencontainers.image.revision` label.

1. Pull the image and read its revision label:
   `docker pull ghcr.io/hamzaahmedsharif/docmind-service:sha-<sha7>`
   `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' <image>`
2. Run it with the non-secret release configuration and the three secrets forwarded from the environment (never on the command line):
   `docker run -d --name release-smoke --memory 512m -p 127.0.0.1:8000:8000 --env-file deploy/release.env -e DOCMIND_DATABASE_URL -e DOCMIND_DATABASE_URL_DIRECT -e DOCMIND_LLM_API_KEY <image>`
3. Run the release smoke:
   `python scripts/smoke_http.py --base http://127.0.0.1:8000 --mode ephemeral --expect-commit <sha> --expect-image-revision <sha> --check-limits --json-out smoke.json`
4. Local fallback when the production secrets are not stored in GitHub:
   `scripts/run_release_local.ps1` (reads `deploy/release.env`, `.env.neon` and `.env`; never prints them).

## Variable list (secret vs not)

| Variable | Secret? | Description |
|---|---|---|
| `DOCMIND_LLM_API_KEY` | yes | Groq key for hosted provider |
| `DOCMIND_DATABASE_URL` | yes | Pooled connection string |
| `DOCMIND_DATABASE_URL_DIRECT` | yes | Direct connection string |
| `DOCMIND_LLM_PROVIDER` | no | `fake` or `hosted` |
| `DOCMIND_ENVIRONMENT` | no | `dev`, `test`, `prod` |
| `DOCMIND_UPLOADS_ENABLED` | no | `true` / `false` |
| `DOCMIND_TRUST_PROXY_HOPS` | no | `0` or `1` |
| `DOCMIND_AUTO_MIGRATE` | no | `true` / `false` |
| `DOCMIND_DEMO_DAILY_CAP` | no | Daily question cap (UTC day) |
| `DOCMIND_DEMO_IP_PER_MIN` | no | Per-IP questions per minute |
| `DOCMIND_GIT_SHA` | no | Commit baked into the image |
| `DOCMIND_GLOBAL_DAILY_LLM_CAP` | no | Global request cap (M6) |
| `DOCMIND_EVIDENCE_MIN_SCORE` | no | Evidence gate threshold (M6) |
| `DOCMIND_CACHE_ENABLED` | no | Cache default (M6) |
| `DOCMIND_CACHE_THRESHOLD` | no | Cache similarity threshold (M6) |

## Rotate each secret

1. Generate a new value in the provider console (e.g., Groq key, Neon password).
2. Add the new value to the secret store used by the deployment (GitHub environment secret or the local `.env.neon`/`.env`).
3. Redeploy or restart the service.
4. Run the release smoke (or the local fallback) and confirm it passes.
5. Remove the old secret.

## M5 specific

- Neon scales to zero after 5 minutes idle; the pooled connection string reconnects.
- `UPLOADS_ENABLED=false` disables `POST/DELETE /v1/documents` (returns 403).
- Per-IP limiter: `DEMO_IP_PER_MIN=5` (sliding 60-second window).
- Daily cap: `DEMO_DAILY_CAP=300` (UTC day, resets at midnight).
- The release smoke runs on every green `main` CI run and costs at most one provider request.
