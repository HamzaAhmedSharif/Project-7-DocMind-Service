import hashlib
import re
from collections import OrderedDict
from threading import Lock

import numpy as np
from fastembed import TextEmbedding

from docmind_service.metrics import EMBED, timer

_QUERY_CACHE_SIZE = 256
_TOKEN = re.compile(r"\w+", re.UNICODE)


class OnnxEmbedder:
    """fastembed ONNX sentence-transformer; the same 384-d model family as P6."""

    dim = 384

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        *,
        cache_dir: str | None = None,
        threads: int = 1,
    ):
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir, threads=threads)
        self._model_lock = Lock()
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_lock = Lock()

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        with self._model_lock:
            vectors = np.asarray(list(self._model.embed(texts, batch_size=32)), dtype=np.float32)
        if vectors.shape != (len(texts), self.dim):
            raise RuntimeError(
                f"embedder returned {vectors.shape}, expected {(len(texts), self.dim)}"
            )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.allclose(norms, 1.0, atol=1e-3):
            vectors = vectors / np.maximum(norms, 1e-12)
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        with self._cache_lock:
            cached = self._cache.get(text)
            if cached is not None:
                self._cache.move_to_end(text)
                return cached
        with timer(EMBED):
            vector = self.embed_passages([text])[0]
        with self._cache_lock:
            self._cache[text] = vector
            while len(self._cache) > _QUERY_CACHE_SIZE:
                self._cache.popitem(last=False)
        return vector

    def warm_up(self) -> None:
        self.embed_query("warm up")

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()


class HashingEmbedder:
    """Deterministic, dependency-free embedder for fast unit tests and demos."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return (
            np.stack([self._one(text) for text in texts])
            if texts
            else np.empty((0, self.dim), dtype=np.float32)
        )

    def embed_query(self, text: str) -> np.ndarray:
        return self._one(text)

    def _one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        if not vector.any():
            vector[0] = 1.0
        return vector / np.linalg.norm(vector)
