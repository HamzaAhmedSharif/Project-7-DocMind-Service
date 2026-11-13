"""P7.3 free design check (zero provider calls).

Admissibility gate A1-A4 + Q4 pre-check for the cross-encoder reranker
design (Claude ruling 2026-11-13). Run from the repo root with the
docmind-service env python.

  python -u evaluation/p73_design_check.py --model-dir <dir> \
      --model-id Xenova/ms-marco-MiniLM-L-6-v2 \
      --out evaluation/results/p73-design-check.json

--model-dir must hold the ONNX cross-encoder (onnx/model_quantized.onnx
or onnx/model.onnx) plus tokenizer.json. Omit --model-dir to run the
dense-only stages (A1, token fit, Q4 dense baseline) without a reranker.

Dense rankings come from the frozen reference vectors
(evaluation/fixtures/reference_*.npy), exactly as the P7.2 diagnostic
did -- no embedding model is loaded here. The reranker runs locally via
onnxruntime + tokenizers: fastembed 0.9.1 (the pinned version) has no
TextCrossEncoder class, so this is the ruling's pre-authorised fallback
(upgrading fastembed would need a lock refresh plus E1/E2 and
determinism re-checks, which the ruling rules out for P7.3).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from evaluation.questions import QUESTIONS  # noqa: E402
from evaluation.scoring import clean, score_key_facts  # noqa: E402

ROOT = Path(".")
N_CANDIDATES = 25
TOP_K = 10
STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "what",
    "how",
    "why",
    "which",
    "in",
    "on",
    "of",
    "for",
    "to",
    "by",
    "and",
    "or",
    "with",
    "as",
    "at",
    "from",
    "it",
    "its",
    "this",
    "that",
}


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS


def term_overlap(question, context):
    q = words(question)
    if not q:
        return 0.0
    return len(q & words(context)) / len(q)


class CrossEncoder:
    """ONNX cross-encoder via onnxruntime + tokenizers (no fastembed)."""

    def __init__(self, model_dir, sub_batch=0):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = Path(model_dir)
        onnx_path = d / "onnx" / "model_quantized.onnx"
        if not onnx_path.exists():
            onnx_path = d / "onnx" / "model.onnx"
        if not onnx_path.exists():
            raise FileNotFoundError(f"no ONNX model under {d / 'onnx'}")
        self.onnx_path = onnx_path
        self.onnx_bytes = onnx_path.stat().st_size
        self.tokenizer = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self.input_names = [i.name for i in self.session.get_inputs()]
        # 0 = one full-batch run (the original A1-A4 config). N > 0 scores in
        # N-pair sub-batches, mirroring the shipped adapter (RERANK_BATCH_SIZE).
        # The int8 model's dynamic activation quantization makes scores depend
        # on batch composition, so the two modes can rank differently.
        self.sub_batch = sub_batch

    def score(self, question, passages):
        """Relevance score per passage; higher is more relevant."""
        enc = self.tokenizer.encode_batch([(question, p) for p in passages])
        feed = {}
        arrays = {
            "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64),
        }
        for name in self.input_names:
            if name in arrays:
                feed[name] = arrays[name]
        if self.sub_batch and len(passages) > self.sub_batch:
            parts = []
            for start in range(0, len(passages), self.sub_batch):
                sub = {name: arr[start : start + self.sub_batch] for name, arr in feed.items()}
                batch_logits = self.session.run(None, sub)[0]
                batch_logits = np.asarray(batch_logits, dtype=np.float64)
                parts.append(batch_logits[:, 0] if batch_logits.ndim == 2 else batch_logits)
            return np.concatenate(parts)
        logits = self.session.run(None, feed)[0]
        logits = np.asarray(logits, dtype=np.float64)
        return logits[:, 0] if logits.ndim == 2 else logits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--out", default="evaluation/results/p73-design-check.json")
    ap.add_argument("--sub-batch", type=int, default=0)
    args = ap.parse_args()

    chunks = load("data/work/chunks.json")
    text_by_ordinal = {c["ordinal"]: c["text"] for c in chunks}
    top10_fix = load("evaluation/fixtures/reference_top10.json")
    meta = load("evaluation/fixtures/reference_meta.json")
    qvec = np.load(ROOT / "evaluation/fixtures/reference_question_vectors.npy")
    cvec = np.load(ROOT / "evaluation/fixtures/reference_chunk_vectors.npy")
    q_index = {qid: i for i, qid in enumerate(meta["question_ids"])}
    p72 = load("evaluation/results/service-eval-p72.json")

    doc_qs = [q for q in QUESTIONS if q["type"] == "doc"]
    abs_qs = [q for q in QUESTIONS if q["type"] == "absent"]

    def dense_ranking(qid):
        sims = cvec @ qvec[q_index[qid]]
        order = list(np.argsort(-sims))
        return order, {int(o): float(sims[o]) for o in order}

    # ---- A1: harness validity (dense-only reproduction) ----
    ceiling = 0
    top10_match_all = True
    ranks = {}
    baseline_present = {}  # (qid, fact idx) -> bool
    baseline_ctx_chars = {}
    for q in doc_qs:
        qid = q["id"]
        ranking, _ = dense_ranking(qid)
        top10_set = set(int(o) for o in ranking[:TOP_K])
        top10_match_all &= top10_set == set(top10_fix[qid])
        context = "\n".join(text_by_ordinal[o] for o in sorted(top10_set))
        baseline_ctx_chars[qid] = sum(len(text_by_ordinal[o]) for o in top10_set)
        ctx = score_key_facts(context, q["key_facts"])
        ceiling += ctx["found"]
        rank_of = {int(o): i + 1 for i, o in enumerate(ranking)}
        for i, (fact, present) in enumerate(zip(q["key_facts"], ctx["hits"], strict=True)):
            baseline_present[(qid, i)] = bool(present)
            if not present:
                bearing = [
                    o
                    for o, t in text_by_ordinal.items()
                    if re.search(fact["answer_regex"], clean(t), re.IGNORECASE)
                ]
                ranks[f"{qid}:{fact['fact'][:40]}"] = (
                    min(rank_of[int(o)] for o in bearing) if bearing else None
                )
    a1 = {
        "C_recomputed": ceiling,
        "C_expected": 23,
        "top10_matches_reference_all": bool(top10_match_all),
        "absent_fact_best_ranks": ranks,
        "pass": bool(ceiling == 23 and top10_match_all),
    }

    # ---- Token fit: prompt_tokens ~ O + slope * context chars ----
    xs, ys = [], []
    for run in ("A3", "B3"):
        for row in p72["runs"][run]["questions"]:
            if (
                row["calls"] == 1
                and row["status"] == 200
                and not row["refused"]
                and row["id"] in baseline_ctx_chars
            ):
                xs.append(baseline_ctx_chars[row["id"]])
                ys.append(row["prompt_tokens"])
    xs_arr, ys_arr = np.array(xs, dtype=float), np.array(ys, dtype=float)
    slope, intercept = np.polyfit(xs_arr, ys_arr, 1)
    resid = ys_arr - (intercept + slope * xs_arr)
    token_fit = {
        "n_points": len(xs),
        "slope_tokens_per_char": float(slope),
        "intercept_overhead_tokens": float(intercept),
        "resid_std": float(resid.std()),
        "resid_max_abs": float(np.abs(resid).max()),
        "note": "single-call A3/B3 doc prompts (calls==1, status 200, "
        "not refused); x = total chars of the dense top-10 context",
    }

    out = {
        "a1_harness_validity": a1,
        "token_fit": token_fit,
        "model": None,
        "a2": None,
        "a3": None,
        "a4": None,
        "q4_precheck": {},
        "per_question": {},
        "rerank_latency_ms": None,
        "f1_fallback_k12": None,
        "admissible_a1_a4": None,
    }

    # ---- Q4 dense baseline (no model needed) ----
    for q in abs_qs:
        qid = q["id"]
        ranking, sims = dense_ranking(qid)
        top10 = [int(o) for o in ranking[:TOP_K]]
        context = "\n".join(text_by_ordinal[o] for o in top10)
        out["q4_precheck"][qid] = {
            "dense_top1_score": float(sims[ranking[0]]),
            "dense_top10": top10,
            "dense_top10_scores": [round(float(sims[o]), 4) for o in top10],
            "term_overlap_baseline": round(term_overlap(q["question"], context), 3),
        }

    if not args.model_dir:
        out["note"] = "dense-only run: rerank stages skipped (no --model-dir)"
        Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(json.dumps(out, indent=1))
        return 0

    # ---- Reranked contexts ----
    ce = CrossEncoder(args.model_dir, sub_batch=args.sub_batch)
    out["model"] = {
        "id": args.model_id,
        "route": "onnxruntime + tokenizers (fastembed 0.9.1 has no "
        "TextCrossEncoder; ruling fallback)",
        "onnx_file": ce.onnx_path.name,
        "onnx_bytes": ce.onnx_bytes,
        "sub_batch": args.sub_batch,
    }
    latencies = []
    c_prime = 0
    lost, gained = [], []
    per_q = {}
    for q in doc_qs:
        qid = q["id"]
        ranking, sims = dense_ranking(qid)
        cand = [int(o) for o in ranking[:N_CANDIDATES]]
        t0 = time.perf_counter()
        scores = ce.score(q["question"], [text_by_ordinal[o] for o in cand])
        latencies.append((time.perf_counter() - t0) * 1000.0)
        order = sorted(range(len(cand)), key=lambda i: -scores[i])  # stable
        reranked = [cand[i] for i in order]
        final10 = reranked[:TOP_K]
        final12 = reranked[:12]
        ctx10 = "\n".join(text_by_ordinal[o] for o in final10)
        ctx12 = "\n".join(text_by_ordinal[o] for o in final12)
        scored10 = score_key_facts(ctx10, q["key_facts"])
        scored12 = score_key_facts(ctx12, q["key_facts"])
        c_prime += scored10["found"]
        chars10 = sum(len(text_by_ordinal[o]) for o in final10)
        chars12 = sum(len(text_by_ordinal[o]) for o in final12)
        for i, (fact, present) in enumerate(zip(q["key_facts"], scored10["hits"], strict=True)):
            base = baseline_present[(qid, i)]
            if base and not present:
                lost.append({"question": qid, "fact": fact["fact"]})
            if present and not base:
                gained.append({"question": qid, "fact": fact["fact"]})
        per_q[qid] = {
            "dense_top10": [int(o) for o in ranking[:TOP_K]],
            "reranked_top10": final10,
            "reranked_top12": final12,
            "present_baseline": sum(
                1 for i in range(len(q["key_facts"])) if baseline_present[(qid, i)]
            ),
            "present_reranked_k10": scored10["found"],
            "present_reranked_k12": scored12["found"],
            "facts_total": scored10["total"],
            "context_chars_k10": chars10,
            "projected_prompt_tokens_k10": float(intercept + slope * chars10),
            "context_chars_k12": chars12,
            "projected_prompt_tokens_k12": float(intercept + slope * chars12),
            "rerank_scores_top10": [round(float(scores[cand.index(o)]), 4) for o in final10],
        }
    out["per_question"] = per_q
    lat = np.array(latencies, dtype=float)
    out["rerank_latency_ms"] = {
        "p50": float(np.percentile(lat, 50)),
        "p95": float(np.percentile(lat, 95)),
        "max": float(lat.max()),
        "n_questions": len(latencies),
        "note": "unconstrained laptop profile, 25 pairs per question",
    }

    d02_final = per_q["d02"]["reranked_top10"]
    d09_final = per_q["d09"]["reranked_top10"]
    out["a2"] = {
        "d02_chunk11_in_context": 11 in d02_final,
        "d02_chunk11_rerank_position": (d02_final.index(11) + 1 if 11 in d02_final else None),
        "d09_chunk27_in_context": 27 in d09_final,
        "d09_chunk27_rerank_position": (d09_final.index(27) + 1 if 27 in d09_final else None),
        "pass": bool(11 in d02_final and 27 in d09_final),
    }
    out["a3"] = {
        "C_prime": c_prime,
        "C_prime_expected": 26,
        "lost_facts": lost,
        "gained_facts": gained,
        "pass": bool(not lost and c_prime == 26),
    }
    proj10 = float(np.mean([per_q[q["id"]]["projected_prompt_tokens_k10"] for q in doc_qs]))
    proj12 = float(np.mean([per_q[q["id"]]["projected_prompt_tokens_k12"] for q in doc_qs]))
    out["a4"] = {
        "projected_mean_prompt_tokens_k10": proj10,
        "limit": 3000,
        "pass": bool(proj10 <= 3000),
        "note": "mean over the 12 doc questions of the fitted projection "
        "on the reranked top-10 contexts",
    }
    out["f1_fallback_k12"] = {
        "C_prime_k12": sum(per_q[q["id"]]["present_reranked_k12"] for q in doc_qs),
        "projected_mean_prompt_tokens_k12": proj12,
        "note": "informational; F1 applies only if P fails admissibility "
        "for all three candidate models",
    }

    # ---- Q4 reranked arm ----
    for q in abs_qs:
        qid = q["id"]
        ranking, sims = dense_ranking(qid)
        cand = [int(o) for o in ranking[:N_CANDIDATES]]
        scores = ce.score(q["question"], [text_by_ordinal[o] for o in cand])
        order = sorted(range(len(cand)), key=lambda i: -scores[i])
        reranked = [cand[i] for i in order]
        final10 = reranked[:TOP_K]
        context = "\n".join(text_by_ordinal[o] for o in final10)
        out["q4_precheck"][qid].update(
            {
                "reranked_top10": final10,
                "rerank_scores_top10": [round(float(scores[cand.index(o)]), 4) for o in final10],
                "term_overlap_reranked": round(term_overlap(q["question"], context), 3),
            }
        )

    out["admissible_a1_a4"] = bool(
        a1["pass"] and out["a2"]["pass"] and out["a3"]["pass"] and out["a4"]["pass"]
    )
    Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "a1": a1,
                "token_fit": token_fit,
                "model": out["model"],
                "a2": out["a2"],
                "a3": {
                    "C_prime": c_prime,
                    "lost": lost,
                    "gained": gained,
                    "pass": out["a3"]["pass"],
                },
                "a4": out["a4"],
                "rerank_latency_ms": out["rerank_latency_ms"],
                "f1_fallback_k12": out["f1_fallback_k12"],
                "admissible_a1_a4": out["admissible_a1_a4"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
