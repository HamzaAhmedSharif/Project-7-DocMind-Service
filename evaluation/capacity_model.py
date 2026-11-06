"""Capacity model (Master Script 10.3).

A pure function of committed inputs: provider limits (response headers plus the
provider's published free-plan table), the pooled token means of service-eval
runs A and B, the M7 service-side throughput inputs, and the M6 cache test-half
hit rate. Writes evaluation/results/capacity-m8.json and the generated table
in docs/CAPACITY.md. No provider calls.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"

# Groq published free-plan limits for openai/gpt-oss-120b, retrieved 2026-11-06
# (console.groq.com/docs/rate-limits): RPM 30, RPD 1,000, TPM 8,000, TPD 200,000.
# The TPM and RPD values match the live response headers in provider-limits.json.
DOCUMENTED_RPM = 30
DOCUMENTED_TPD = 200_000
PACING = 0.9
GLOBAL_CAP = 800
DEMO_DAILY_CAP = 300
DEMO_PER_IP_PER_MIN = 5
CALLS_PER_QUERY = 1
MULTI_TOKEN_RATIO = 5856 / 2559  # Project 6 multi-agent vs single-call prompt tokens
MULTI_CALL_FACTOR = 3.1  # Project 6 derived comparator (Master Script 10.3)


def capacity(inputs: dict) -> dict:
    tokens_per_query = inputs["mean_prompt_tokens"] + inputs["mean_completion_tokens"]
    qpm_tokens = PACING * inputs["tpm"] / tokens_per_query
    qpm_requests = PACING * inputs["rpm"] / inputs["calls_per_query"]
    qpm = min(qpm_tokens, qpm_requests)
    daily = min(inputs["rpd"], inputs["global_cap"])
    if inputs.get("tpd"):
        daily = min(daily, inputs["tpd"] / tokens_per_query)
    served = {label: daily / (1 - h) for label, h in inputs["cache_scenarios"].items()}
    in_flight = qpm * (inputs["mean_api_seconds"] / 60)
    multi_tokens = tokens_per_query * inputs["multi_token_ratio"]
    multi_daily = min(inputs["rpd"], inputs["global_cap"])
    if inputs.get("tpd"):
        multi_daily = min(multi_daily, inputs["tpd"] / multi_tokens)
    return {
        "tokens_per_query": tokens_per_query,
        "qpm_tokens": qpm_tokens,
        "qpm_requests": qpm_requests,
        "qpm": qpm,
        "daily_provider_bound_answered": daily,
        "served_per_day_scenarios": served,
        "in_flight_provider_calls": in_flight,
        "multi_agent_derived": {
            "label": "derived from Project 6 measurements; "
            "the service does not implement multi mode",
            "tokens_per_query": multi_tokens,
            "calls_per_query": inputs["calls_per_query"] * inputs["multi_call_factor"],
            "qpm": PACING * inputs["tpm"] / multi_tokens,
            "daily_provider_bound_answered": multi_daily,
        },
    }


def pooled_answered(service_eval: dict) -> dict:
    prompts, completions, api_seconds = [], [], []
    for run in ("A", "B"):
        for question in service_eval["runs"][run]["questions"]:
            if not question["refused"] and question["status"] == 200:
                prompts.append(question["prompt_tokens"])
                completions.append(question["completion_tokens"])
                if question.get("api_seconds") is not None:
                    api_seconds.append(question["api_seconds"])
    return {
        "n": len(prompts),
        "mean_prompt_tokens": sum(prompts) / len(prompts),
        "mean_completion_tokens": sum(completions) / len(completions),
        "mean_api_seconds": sum(api_seconds) / len(api_seconds),
    }


def build_inputs() -> dict:
    limits = json.loads((RESULTS / "provider-limits.json").read_text(encoding="utf-8"))
    headers = limits["headers"]
    service_eval = json.loads((RESULTS / "service-eval-m8.json").read_text(encoding="utf-8"))
    pooled = pooled_answered(service_eval)
    cache = json.loads((RESULTS / "cache-m6.json").read_text(encoding="utf-8"))
    hit_rate = cache["test"]["same_intent_hit_rate"]
    service = json.loads((RESULTS / "capacity-inputs-m7.json").read_text(encoding="utf-8"))
    return {
        "tpm": int(headers["x-ratelimit-limit-tokens"]),
        "rpd": int(headers["x-ratelimit-limit-requests"]),
        "rpm": DOCUMENTED_RPM,
        "tpd": DOCUMENTED_TPD,
        "mean_prompt_tokens": pooled["mean_prompt_tokens"],
        "mean_completion_tokens": pooled["mean_completion_tokens"],
        "mean_api_seconds": pooled["mean_api_seconds"],
        "calls_per_query": CALLS_PER_QUERY,
        "global_cap": GLOBAL_CAP,
        "demo_daily_cap": DEMO_DAILY_CAP,
        "demo_per_ip_per_min": DEMO_PER_IP_PER_MIN,
        "cache_scenarios": {"h=0": 0.0, "h=measured": hit_rate, "h=0.5": 0.5},
        "multi_token_ratio": MULTI_TOKEN_RATIO,
        "multi_call_factor": MULTI_CALL_FACTOR,
        "service_sustained_rps_render_like": service["sustained_rps"],
        "pooled_answered_n": pooled["n"],
        "cache_hit_rate_measured": hit_rate,
        "sources": {
            "tpm_rpd": "evaluation/results/provider-limits.json (response headers, 2026-11-06)",
            "rpm_tpd": "Groq published free-plan table for openai/gpt-oss-120b, "
            "retrieved 2026-11-06",
            "token_means": "evaluation/results/service-eval-m8.json runs A and B pooled, "
            "answered requests only",
            "service_rps": "evaluation/results/capacity-inputs-m7.json",
            "cache_hit_rate": "evaluation/results/cache-m6.json test half at tau 0.86; a "
            "similarity-evaluation hit rate on a hand-written probe set, not production traffic",
        },
    }


BEGIN = "<!-- BEGIN GENERATED: capacity_model.py -->"
END = "<!-- END GENERATED -->"


def render_block(inputs: dict, outputs: dict) -> str:
    served = outputs["served_per_day_scenarios"]
    multi = outputs["multi_agent_derived"]
    rps = inputs["service_sustained_rps_render_like"]
    lines = [
        BEGIN,
        "| Quantity | Value | Source |",
        "|---|---|---|",
        f"| Mean prompt tokens per answered query | {inputs['mean_prompt_tokens']:.1f} "
        f"| service-eval runs A+B pooled (n={inputs['pooled_answered_n']}) |",
        f"| Mean completion tokens per answered query | "
        f"{inputs['mean_completion_tokens']:.1f} | service-eval runs A+B pooled |",
        f"| Tokens per query | {outputs['tokens_per_query']:.1f} | sum of the two means |",
        f"| Provider tokens per minute (TPM) | {inputs['tpm']} | response headers |",
        f"| Provider requests per minute (RPM) | {inputs['rpm']} | published free-plan table |",
        f"| Provider requests per day (RPD) | {inputs['rpd']} | response headers |",
        f"| Provider tokens per day (TPD) | {inputs['tpd']} | published free-plan table |",
        f"| Queries per minute, token-bound | {outputs['qpm_tokens']:.2f} "
        "| 0.9 x TPM / tokens per query |",
        f"| Queries per minute, request-bound | {outputs['qpm_requests']:.2f} "
        "| 0.9 x RPM / calls per query |",
        f"| Queries per minute (bound) | {outputs['qpm']:.2f} | the smaller of the two |",
        f"| Answered queries per day (provider-bound) | "
        f"{outputs['daily_provider_bound_answered']:.1f} "
        "| min(RPD, 800 global cap, TPD / tokens per query) |",
        f"| Served per day, cache hit rate 0 | {served['h=0']:.1f} | scenario |",
        f"| Served per day, cache hit rate {inputs['cache_hit_rate_measured']:.4f} (measured) "
        f"| {served['h=measured']:.1f} | scenario; the measured rate is a "
        "similarity-evaluation hit rate on a hand-written probe set, not production traffic |",
        f"| Served per day, cache hit rate 0.5 | {served['h=0.5']:.1f} | scenario |",
        f"| In-flight provider calls (Little's law) | "
        f"{outputs['in_flight_provider_calls']:.2f} | qpm x mean api_seconds / 60 |",
        f"| Service-side sustained throughput (render-like, fake provider) | "
        f"{rps['concurrency_5']} rps at c5, {rps['concurrency_10']} rps at c10 "
        "| capacity-inputs-m7.json |",
        f"| Multi-agent tokens per query (derived) | {multi['tokens_per_query']:.1f} "
        "| Project 6 ratio 5856/2559 applied to the measured token use |",
        f"| Multi-agent answered per day (derived) | "
        f"{multi['daily_provider_bound_answered']:.1f} "
        "| derived from Project 6 measurements; the service does not implement multi mode |",
        "",
        f"Bottleneck: the provider's token limits bound throughput "
        f"({outputs['qpm']:.2f} queries/minute, "
        f"{outputs['daily_provider_bound_answered']:.0f} answered queries/day), not the "
        f"service, which sustains {rps['concurrency_5']} requests/second on the "
        "render-like profile with the provider excluded.",
        END,
    ]
    return "\n".join(lines)


def main() -> int:
    inputs = build_inputs()
    outputs = capacity(inputs)
    payload = {"inputs": inputs, "outputs": outputs}
    (RESULTS / "capacity-m8.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    doc_path = ROOT / "docs" / "CAPACITY.md"
    if doc_path.is_file():
        text = doc_path.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            before, rest = text.split(BEGIN, 1)
            _, after = rest.split(END, 1)
            text = before + render_block(inputs, outputs) + after
            doc_path.write_text(text, encoding="utf-8")
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
