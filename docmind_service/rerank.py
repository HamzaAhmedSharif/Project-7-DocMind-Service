"""Cross-encoder reranking (P7.3).

The dense stage returns N candidates; a local ONNX cross-encoder scores each
(question, chunk) pair and the top ``top_k`` of the reranked order go into the
prompt. Chunk ``score`` values stay the dense cosine, so the evidence gate
(still a dense top-1 test) and the citation contract are unchanged.

The adapter uses onnxruntime + tokenizers directly: the pinned fastembed
0.9.1 has no TextCrossEncoder, and the ruling authorises this branch
instead of a fastembed upgrade. Tokenization mirrors the P7.3 design check
(``evaluation/p73_design_check.py``) exactly, so the admissibility results
(A1-A4) describe this code.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from docmind_service.domain import RetrievedChunk
from docmind_service.metrics import RERANK_SECONDS, RERANK_TOTAL, timer

logger = logging.getLogger("docmind_service.rerank")

MAX_SEQUENCE_LENGTH = 512

# Pairs scored per ORT run. A full 25-pair batch grows the ORT arena to
# ~1 GB (measured 2026-11-13: the 512 MB container OOM'd); 5-pair runs
# keep the arena small. Scores are identical to a full batch: pairs are
# independent (padding is masked), so splitting changes nothing.
RERANK_BATCH_SIZE = 5


class Reranker(Protocol):
    """Reorders retrieved chunks by cross-encoder relevance; never changes scores."""

    name: str

    def rerank(self, question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...

    def warm_up(self) -> None: ...


class OnnxCrossEncoderReranker:
    """MiniLM cross-encoder over ONNX Runtime.

    Layout under ``cache_dir``: ``<model-id>/onnx/model_quantized.onnx``
    (int8; falls back to ``onnx/model.onnx``) plus ``<model-id>/tokenizer.json``.
    The model is baked into the image at build time (``COPY models/``) and
    fetched for CI by ``scripts/fetch_reranker.py``; it is never downloaded
    at runtime.

    Inference is serialised with a lock: ORT ``session.run`` is
    thread-safe, but concurrent 25-pair runs each allocate large
    activation buffers and OOM the 512 MB container (measured
    2026-11-13: 10 concurrent queries killed it at 495 MB). This
    mirrors the embedder's lock in ``embedding.py``. Scores are
    unaffected — concurrent calls queue, they do not change.

    Pairs are scored in sub-batches (``RERANK_BATCH_SIZE``) and the
    CPU memory arena is disabled: a full 25-pair batch grows the
    arena to ~1 GB even serialised, which the 512 MB container
    cannot hold. Sub-batching keeps the live tensors small and the
    arena off keeps nothing retained between runs.
    """

    def __init__(self, model_name: str, *, cache_dir: str | Path | None):
        if cache_dir is None:
            raise ValueError(
                "a model cache directory is required when the reranker is enabled "
                "(DOCMIND_MODEL_CACHE_DIR)"
            )
        model_dir = Path(cache_dir) / model_name
        onnx_path = model_dir / "onnx" / "model_quantized.onnx"
        if not onnx_path.is_file():
            onnx_path = model_dir / "onnx" / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"
        if not onnx_path.is_file():
            raise FileNotFoundError(f"reranker model not found under {model_dir / 'onnx'}")
        if not tokenizer_path.is_file():
            raise FileNotFoundError(f"reranker tokenizer not found under {model_dir}")
        self.name = model_name
        self.model_dir = model_dir
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=MAX_SEQUENCE_LENGTH)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(
            str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = [entry.name for entry in self._session.get_inputs()]
        self._lock = threading.Lock()

    def rerank(self, question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return []
        encodings = self._tokenizer.encode_batch([(question, chunk.text) for chunk in chunks])
        arrays = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
        }
        feed = {name: arrays[name] for name in self._input_names if name in arrays}
        parts = []
        with self._lock:
            for start in range(0, len(chunks), RERANK_BATCH_SIZE):
                sub = {name: arr[start : start + RERANK_BATCH_SIZE] for name, arr in feed.items()}
                logits = np.asarray(self._session.run(None, sub)[0], dtype=np.float64)
                parts.append(logits[:, 0] if logits.ndim == 2 else logits)
        scores = np.concatenate(parts)
        # Stable sort: ties keep the dense (candidate) order, as in the design check.
        order = sorted(range(len(chunks)), key=lambda i: -scores[i])
        return [chunks[i] for i in order]

    def warm_up(self) -> None:
        self.rerank(
            "warm up",
            [
                RetrievedChunk(
                    chunk_id="warmup",
                    document_id=uuid4(),
                    page=0,
                    text="warm up",
                    score=0.0,
                )
            ],
        )


class NoopReranker:
    """Explicit no-op: returns the dense order unchanged."""

    name = "noop"

    def rerank(self, question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return list(chunks)

    def warm_up(self) -> None:
        return None


class FakeReranker:
    """Deterministic test double: reverses the candidate order."""

    name = "fake"

    def rerank(self, question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return list(reversed(chunks))

    def warm_up(self) -> None:
        return None


def rerank_with_fallback(
    reranker: Reranker, question: str, chunks: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """Rerank, or fall back to the dense order when the reranker fails.

    A failure never fails the request: the dense order is returned, the
    exception TYPE only is logged (never the message, question or chunk
    text), and the fallback is counted. A reranker that changes the chunk
    count is treated as a failure. Fewer than two chunks need no rerank.
    """
    if reranker is None or len(chunks) < 2:
        return list(chunks)
    try:
        with timer(RERANK_SECONDS):
            ordered = reranker.rerank(question, chunks)
        if len(ordered) != len(chunks):
            raise RuntimeError("reranker changed the chunk count")
        RERANK_TOTAL.labels(result="ok").inc()
        return list(ordered)
    except Exception as exc:  # noqa: BLE001 - any reranker failure degrades to dense order
        logger.warning("rerank fallback [%s]", type(exc).__name__)
        RERANK_TOTAL.labels(result="fallback").inc()
        return list(chunks)
