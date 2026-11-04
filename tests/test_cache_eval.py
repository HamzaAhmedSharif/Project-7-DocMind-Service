import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from evaluation.cache_eval import run_cache_eval as cache_eval
from evaluation.questions import QUESTIONS


def _pairs():
    path = Path(cache_eval.__file__).with_name("pairs.json")
    return json.loads(path.read_text(encoding="utf-8"))["pairs"]


def test_pairs_have_enough_probes_and_an_even_split():
    pairs = _pairs()
    same = [probe for probe in pairs if probe["label"] == "same"]
    different = [probe for probe in pairs if probe["label"] == "different"]
    assert len(same) >= 40
    assert len(different) >= 30
    assert sum(1 for probe in different if int(probe["id"][1:]) % 2 == 1) >= 15
    assert sum(1 for probe in different if int(probe["id"][1:]) % 2 == 0) >= 15
    base_ids = {question["id"] for question in QUESTIONS}
    for probe in pairs:
        assert probe["base"] in base_ids
        if probe["label"] == "different":
            assert probe["why_different"].strip()


def test_cosine_handles_zero_and_identical_vectors():
    assert cache_eval.cosine(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == pytest.approx(1.0)
    assert cache_eval.cosine(np.zeros(2), np.array([1.0, 0.0])) == 0.0
    assert cache_eval.cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == 0.0


def test_metrics_computes_hit_rate_and_false_hit_share():
    probes = [
        {"id": "s01", "label": "same"},
        {"id": "s02", "label": "same"},
        {"id": "x01", "label": "different"},
        {"id": "x02", "label": "different"},
    ]
    similarities = {"s01": 0.95, "s02": 0.5, "x01": 0.4, "x02": 0.99}
    row = cache_eval._metrics(probes, similarities, 0.9)
    assert row["same_hits"] == 1
    assert row["same_intent_hit_rate"] == 0.5
    assert row["different_hits"] == 1
    assert row["false_hit_share"] == 0.5


def test_validate_rejects_a_bad_probe():
    with pytest.raises(ValueError):
        cache_eval._validate([{"id": "s01", "base": "d99", "text": "x", "label": "same"}], {"d01"})
    with pytest.raises(ValueError):
        cache_eval._validate(
            [{"id": "x01", "base": "d01", "text": "x", "label": "different"}], {"d01"}
        )


class FakeEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed_query(self, text):
        return np.array([1.0, 0.0])

    def embed_passages(self, texts):
        return np.array([self.vectors[text] for text in texts])


def test_main_selects_on_calibration_and_reports_the_test_half(tmp_path, monkeypatch):
    same = []
    different = []
    vectors = {}
    for index in range(1, 41):
        probe_id = f"s{index:02d}"
        text = f"same probe {index}"
        same.append({"id": probe_id, "base": "d01", "text": text, "label": "same"})
        vectors[text] = np.array([0.99, 0.01])
    for index in range(1, 31):
        probe_id = f"x{index:02d}"
        text = f"different probe {index}"
        different.append(
            {
                "id": probe_id,
                "base": "d01",
                "text": text,
                "label": "different",
                "why_different": "a different information need",
            }
        )
        vectors[text] = np.array([0.8, 0.6]) if index % 2 else np.array([0.99, 0.01])
    pairs = {"pairs": same + different}
    pairs_path = tmp_path / "pairs.json"
    pairs_path.write_text(json.dumps(pairs), encoding="utf-8")
    monkeypatch.setattr(cache_eval, "OnnxEmbedder", lambda *args, **kwargs: FakeEmbedder(vectors))
    out = tmp_path / "cache.json"
    assert cache_eval.main(["--pairs", str(pairs_path), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["pairs_hash"] == hashlib.sha256(pairs_path.read_bytes()).hexdigest()
    assert result["selected_threshold"] == 0.81
    assert result["c1_false_hit_share"] == 1.0
    assert result["cache_enabled_default"] is False
    assert len(result["curves"]["calibration"]) == 30
    assert len(result["curves"]["test"]) == 30
    assert result["provider_requests"] == 0
    assert result["probe_counts"]["different_test"] == 15
