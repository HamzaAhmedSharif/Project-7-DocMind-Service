"""Print RSS checkpoints for a fresh process. Run with the service Python."""

import json
import os
import sys

import psutil

RSS = {}


def mark(name):
    RSS[name] = round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)


mark("start")
from docmind_service.embedding import OnnxEmbedder  # noqa: E402

mark("after_import")
embedder = OnnxEmbedder(cache_dir=os.environ.get("DOCMIND_MODEL_CACHE_DIR"))
mark("after_model_load")
texts = [" ".join(["word"] * 150) for _ in range(100)]
embedder.embed_passages(texts)
mark("after_100_passages")
print(json.dumps(RSS))
sys.exit(0)
