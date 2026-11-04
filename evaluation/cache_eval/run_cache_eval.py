"""Cache calibration C1: same-intent hit rate and false-hit share (M6.7)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from docmind_service.config import Settings
from docmind_service.embedding import OnnxEmbedder
from evaluation.questions import QUESTIONS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAIRS = Path(__file__).with_name("pairs.json")
THRESHOLDS = [round(0.70 + index * 0.01, 2) for index in range(30)]


def cosine(a, b) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def _metrics(probes: list[dict], similarities: dict[str, float], threshold: float) -> dict:
    same = [probe for probe in probes if probe["label"] == "same"]
    different = [probe for probe in probes if probe["label"] == "different"]
    same_hits = sum(1 for probe in same if similarities[probe["id"]] >= threshold)
    different_hits = sum(1 for probe in different if similarities[probe["id"]] >= threshold)
    return {
        "threshold": threshold,
        "same_total": len(same),
        "same_hits": same_hits,
        "same_intent_hit_rate": same_hits / len(same) if same else 0.0,
        "different_total": len(different),
        "different_hits": different_hits,
        "false_hit_share": different_hits / len(different) if different else 0.0,
    }


def _validate(probes: list[dict], base_ids: set[str]) -> None:
    seen = set()
    for probe in probes:
        if probe["id"] in seen:
            raise ValueError(f"duplicate probe id {probe['id']}")
        seen.add(probe["id"])
        if probe["base"] not in base_ids:
            raise ValueError(f"{probe['id']} has unknown base {probe['base']}")
        if probe["label"] not in {"same", "different"}:
            raise ValueError(f"{probe['id']} has invalid label {probe['label']}")
        if probe["label"] == "different" and not probe.get("why_different"):
            raise ValueError(f"{probe['id']} is different but has no why_different")
    same = sum(1 for probe in probes if probe["label"] == "same")
    different = sum(1 for probe in probes if probe["label"] == "different")
    if same < 40 or different < 30:
        raise ValueError(f"need at least 40 same and 30 different probes, got {same}/{different}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "evaluation" / "results" / "cache-m6.json"))
    parser.add_argument("--pairs", default=str(DEFAULT_PAIRS))
    args = parser.parse_args(argv)

    pairs_path = Path(args.pairs)
    raw_pairs = pairs_path.read_bytes()
    probes = json.loads(raw_pairs)["pairs"]
    base_questions = {
        question["id"]: question["question"]
        for question in QUESTIONS
        if question["id"].startswith(("d", "a"))
    }
    _validate(probes, set(base_questions))

    calibration = [probe for probe in probes if int(probe["id"][1:]) % 2 == 1]
    test = [probe for probe in probes if int(probe["id"][1:]) % 2 == 0]

    settings = Settings(_env_file=None)
    embedder = OnnxEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir)
    base_ids = sorted({probe["base"] for probe in probes})
    base_vectors = {base_id: embedder.embed_query(base_questions[base_id]) for base_id in base_ids}
    probe_vectors = embedder.embed_passages([probe["text"] for probe in probes])
    similarities = {
        probe["id"]: cosine(vector, base_vectors[probe["base"]])
        for probe, vector in zip(probes, probe_vectors, strict=True)
    }

    curves = {
        "calibration": [_metrics(calibration, similarities, tau) for tau in THRESHOLDS],
        "test": [_metrics(test, similarities, tau) for tau in THRESHOLDS],
    }
    selected = next(
        (row["threshold"] for row in curves["calibration"] if row["false_hit_share"] <= 0.02),
        THRESHOLDS[-1],
    )
    calibration_at = next(row for row in curves["calibration"] if row["threshold"] == selected)
    test_at = next(row for row in curves["test"] if row["threshold"] == selected)
    cache_default = test_at["false_hit_share"] <= 0.05 and test_at["same_intent_hit_rate"] >= 0.25

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": settings.embedding_model,
        "pairs_file": pairs_path.name,
        "pairs_hash": hashlib.sha256(raw_pairs).hexdigest(),
        "selection_rule": (
            "smallest tau whose false-hit share on the calibration half is <= 0.02; "
            "the test half is reported at that tau and never used to choose it"
        ),
        "selected_threshold": selected,
        "c1_false_hit_share": test_at["false_hit_share"],
        "c1_same_intent_hit_rate": test_at["same_intent_hit_rate"],
        "cache_enabled_default": cache_default,
        "calibration": calibration_at,
        "test": test_at,
        "probe_counts": {
            "calibration": len(calibration),
            "test": len(test),
            "different_calibration": sum(
                1 for probe in calibration if probe["label"] == "different"
            ),
            "different_test": sum(1 for probe in test if probe["label"] == "different"),
        },
        "similarities": [
            {
                "id": probe["id"],
                "base": probe["base"],
                "label": probe["label"],
                "similarity": round(similarities[probe["id"]], 6),
            }
            for probe in probes
        ],
        "curves": curves,
        "provider_requests": 0,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"tau={selected:.2f} calibration false-hit={calibration_at['false_hit_share']:.4f} "
        f"test hit-rate={test_at['same_intent_hit_rate']:.4f} "
        f"test false-hit={test_at['false_hit_share']:.4f} "
        f"cache_enabled_default={cache_default}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
