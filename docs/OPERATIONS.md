# Operations (M5.4 / M7 skeleton)

## Free-tier behavior

- **Render**: free web service spins down after ~15 minutes idle; the first request after idle takes up to ~1 minute to wake. The service uses a Docker runtime on a free plan with 512 MB memory limit.
- **Neon**: database scales to zero after ~5 minutes of idle connection; connection pooler handles reconnection.

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
| `DOCMIND_GLOBAL_DAILY_LLM_CAP` | no | Global request cap |
| `DOCMIND_EVIDENCE_MIN_SCORE` | no | Evidence gate threshold |
| `DOCMIND_CACHE_ENABLED` | no | Cache default |
| `DOCMIND_CACHE_THRESHOLD` | no | Cache similarity threshold |

## Redeployment

1. Push a new commit to `main` (auto-deploy via Render blueprint `checksPass`, or manual trigger).
2. Or use Render dashboard → "Deploy" button.
3. Or call the Render deploy hook: `curl -fsS -X POST "$RENDER_DEPLOY_HOOK_URL"` (GitHub secret, set in [H5]).

## Rollback

- Render dashboard → "Rollback" button (last successful deploy).
- Or revert the commit that introduced the change and push.

## Rotate each secret

1. Generate a new value in the provider console (e.g., Groq key, Neon password).
2. Add the new value as a new env var in Render/dashboard (do not delete the old one immediately).
3. Redeploy the service.
4. Test that the service works with the new secret.
5. Remove the old secret from Render/dashboard.
6. Update any documentation or `render.yaml` references.

## M5 specific

- Render spins down after 15 min idle; first request after idle wakes in ~1 min.
- Neon scales to zero after 5 min idle.
- `UPLOADS_ENABLED=false` disables `POST/DELETE /v1/documents` (returns 403).
- Per-IP limiter: `DEMO_IP_PER_MIN=5` (reset every minute).
- Daily cap: `DEMO_DAILY_CAP=300` (UTC day, resets at midnight).