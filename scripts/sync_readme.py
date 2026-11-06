"""Regenerate the README gate table from the committed result files
(Master Script 10.6). The block between the GENERATED markers in README.md
is owned by this script; --check exits 1 when the committed block differs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"
BEGIN = "<!-- BEGIN GENERATED: gates -->"
END = "<!-- END GENERATED -->"


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def generate_block() -> str:
    gates = load("../gates.json")["gates"]
    retrieval = load("retrieval-m3.json")["metrics"]
    service = load("service-eval-m8.json")
    run_a = service["metrics"]
    run_b = service["runs"]["B"]["metrics"]
    redteam = load("redteam-m6.json")
    cache = load("cache-m6.json")
    load_m7 = load("load-m7.json")

    def threshold(gate_id: str) -> float:
        return gates[gate_id]["value"]

    lines = [
        BEGIN,
        "| Gate | What it checks | Threshold | Measured |",
        "|---|---|---|---|",
        f"| E1 | Embedding parity, min / mean cosine vs reference | >= 0.995 / >= 0.999 "
        f"| {retrieval['e1_min_cosine']:.3f} / {retrieval['e1_mean_cosine']:.3f} |",
        f"| E2 | Retrieval top-10 overlap vs the FAISS reference | >= {threshold('E2'):.2f} "
        f"| {retrieval['e2_mean_top10_overlap']:.3f} |",
        f"| E3 | Key facts in the retrieved context, d01-d12 | >= {int(threshold('E3'))} / 26 "
        f"† | {int(retrieval['e3_key_facts_found'])} / 26 |",
        f"| S1 | Key facts in answers through the API, run A (run B) | "
        f">= {int(threshold('S1'))} / 26 | {int(run_a['s1_key_facts_found'])} / 26 "
        f"({int(run_b['s1_key_facts_found'])} / 26) - gate not met; analysis in "
        "docs/EVALUATION.md |",
        f"| S2 | Absent questions abstained, run A | >= {int(threshold('S2'))} / 4 "
        f"| {int(run_a['s2_absent_abstained'])} / 4 |",
        f"| S3 | Valid citations / answers with a citation, run A | "
        f">= {threshold('S3a'):.2f} / >= {threshold('S3b'):.2f} "
        f"| {run_a['s3_valid_citation_share']:.2f} / "
        f"{run_a['s3_answers_with_citation_share']:.3f} |",
        f"| S4 | Citations whose chunk supports the fact, run A | "
        f">= {threshold('S4'):.2f} target | {run_a['s4_citation_supports_fact_share']:.3f} |",
        f"| S5 | Mean prompt tokens per answered query, run A | "
        f"<= {int(threshold('S5'))} | {run_a['s5_mean_prompt_tokens']:.0f} |",
        f"| R1 | Injection attacks succeeding, guardrails on (off) | <= 2 / 15 "
        f"| {redteam['r1_attacks_succeeded_guardrails_on']} / 15 "
        f"({redteam['r1_attacks_succeeded_guardrails_off']} / 15) |",
        f"| C1 | Semantic-cache false-hit share, test half | <= {threshold('C1'):.2f} "
        f"| {cache['c1_false_hit_share']:.4f} |",
        f"| L1 | 5xx responses and OOM kills under the load matrix | 0 "
        f"| {int(load_m7['l1_errors_5xx_and_oom'])} |",
        f"| MEM | Peak RSS under load, 512 MB container | <= 480 MB "
        f"| {load_m7['mem_peak_rss_mb']:.1f} MB |",
        "",
        "†: the E3 threshold was changed post-hoc from 24 to 23 (DECISIONS.md, "
        "2026-11-03); the measured value is unchanged. S1 was not re-registered: "
        "the gate stands at 22 and the measured runs fall short, with the cause "
        "analysis in docs/EVALUATION.md.",
        END,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    check_only = "--check" in (argv or [])
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print("README.md is missing the GENERATED gates markers")
        return 1
    before, rest = text.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    updated = before + generate_block() + after
    if check_only:
        if updated != text:
            print("README gate table is out of sync with the result files")
            return 1
        print("README gate table in sync")
        return 0
    readme.write_text(updated, encoding="utf-8")
    print("README gate table regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
