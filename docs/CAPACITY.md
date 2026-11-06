# Capacity model

How much traffic the service can answer on the free tiers it runs on. Every
number in the generated table comes from `evaluation/capacity_model.py` over
committed inputs; re-running the script regenerates the table and
`evaluation/results/capacity-m8.json` identically.

Inputs, and where each is measured:

- Provider limits for `openai/gpt-oss-120b` on the Groq free plan: tokens per
  minute and requests per day from the live response headers
  (`evaluation/results/provider-limits.json`, refreshed 2026-11-06); requests
  per minute and tokens per day from the provider's published free-plan table
  (retrieved 2026-11-06). The header values and the published table agree on
  TPM (8,000) and RPD (1,000).
- Mean prompt and completion tokens per answered query: pooled over
  service-eval runs A and B (`evaluation/results/service-eval-m8.json`),
  answered requests only.
- Service-side throughput: the M7 load matrix on the render-like profile
  (0.1 CPU, 512 MB, fake provider), `evaluation/results/capacity-inputs-m7.json`.
  Provider time is excluded there, by design: it isolates what the service
  itself sustains.
- Cache scenarios: the measured rate is the M6 semantic-cache test-half hit
  rate at the calibrated threshold (`evaluation/results/cache-m6.json`). It is
  a similarity-evaluation hit rate on a hand-written probe set of 38 pairs,
  not production traffic; the 0 and 0.5 rows are bracketing scenarios.

Two further caps bind the anonymous demo before the provider does: the demo
guard allows 300 queries per day in total and 5 per minute per IP
(`DOCMIND_DEMO_DAILY_CAP`, `DOCMIND_DEMO_IP_PER_MIN`). The provider-bound
figures below are therefore the ceiling for keyed traffic; anonymous demo
traffic stops at 300 served queries per day regardless of cache rate.

The multi-agent rows are derived, not measured: the Project 6 prompt-token
ratio (5,856 / 2,559) and call factor (3.1) applied to this service's measured
token use. The service does not implement multi mode.

<!-- BEGIN GENERATED: capacity_model.py -->
| Quantity | Value | Source |
|---|---|---|
| Mean prompt tokens per answered query | 2321.8 | service-eval runs A+B pooled (n=15) |
| Mean completion tokens per answered query | 177.1 | service-eval runs A+B pooled |
| Tokens per query | 2498.9 | sum of the two means |
| Provider tokens per minute (TPM) | 8000 | response headers |
| Provider requests per minute (RPM) | 30 | published free-plan table |
| Provider requests per day (RPD) | 1000 | response headers |
| Provider tokens per day (TPD) | 200000 | published free-plan table |
| Queries per minute, token-bound | 2.88 | 0.9 x TPM / tokens per query |
| Queries per minute, request-bound | 27.00 | 0.9 x RPM / calls per query |
| Queries per minute (bound) | 2.88 | the smaller of the two |
| Answered queries per day (provider-bound) | 80.0 | min(RPD, 800 global cap, TPD / tokens per query) |
| Served per day, cache hit rate 0 | 80.0 | scenario |
| Served per day, cache hit rate 0.3636 (measured) | 125.8 | scenario; the measured rate is a similarity-evaluation hit rate on a hand-written probe set, not production traffic |
| Served per day, cache hit rate 0.5 | 160.1 | scenario |
| In-flight provider calls (Little's law) | 0.25 | qpm x mean api_seconds / 60 |
| Service-side sustained throughput (render-like, fake provider) | 5.806 rps at c5, 4.679 rps at c10 | capacity-inputs-m7.json |
| Multi-agent tokens per query (derived) | 5718.4 | Project 6 ratio 5856/2559 applied to the measured token use |
| Multi-agent answered per day (derived) | 35.0 | derived from Project 6 measurements; the service does not implement multi mode |

Bottleneck: the provider's token limits bound throughput (2.88 queries/minute, 80 answered queries/day), not the service, which sustains 5.806 requests/second on the render-like profile with the provider excluded.
<!-- END GENERATED -->

What the model does not cover: provider latency variance (the mean API time
pools runs A and B; the 503 cluster during run A is recorded in
`reports/M8.md`), cold starts, and any paid tier. If the provider changes its
free-plan numbers, the inputs change and every derived figure moves; the
script, not this prose, is the source of truth.
