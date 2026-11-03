"""Read-only P6 reference fixture builder. Run with the P6 rag environment."""

import importlib.util
import json
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("HF_HUB_OFFLINE", "1")
import faiss  # noqa: E402
import sentence_transformers  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("questions", ROOT / "evaluation" / "questions.py")
questions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(questions)
QUESTIONS = questions.QUESTIONS

chunks = json.loads((ROOT / "data" / "work" / "chunks.json").read_text(encoding="utf-8"))
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
cv = model.encode([c["text"] for c in chunks], normalize_embeddings=True).astype("float32")
qv = model.encode([q["question"] for q in QUESTIONS], normalize_embeddings=True).astype("float32")
index = faiss.IndexFlatL2(cv.shape[1])
index.add(cv)
_, ids = index.search(qv, 10)
out = ROOT / "evaluation" / "fixtures"
out.mkdir(parents=True, exist_ok=True)
np.save(out / "reference_chunk_vectors.npy", cv)
np.save(out / "reference_question_vectors.npy", qv)
(out / "reference_top10.json").write_text(
    json.dumps(
        {q["id"]: [int(i) for i in row] for q, row in zip(QUESTIONS, ids, strict=False)},
        indent=1,
    ),
    encoding="utf-8",
)
(out / "reference_meta.json").write_text(
    json.dumps(
        {
            "sentence_transformers": sentence_transformers.__version__,
            "faiss": faiss.__version__,
            "n_chunks": len(chunks),
            "chunk_words": 150,
            "chunk_overlap": 25,
            "question_ids": [q["id"] for q in QUESTIONS],
            "corpus_sha256": json.loads(
                (ROOT / "evaluation" / "corpus.json").read_text(encoding="utf-8")
            )["corpora"][0]["sha256"],
        },
        indent=1,
    ),
    encoding="utf-8",
)
print(f"wrote {len(chunks)} chunk vectors and {len(QUESTIONS)} question vectors")
