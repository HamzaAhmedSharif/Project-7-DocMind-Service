"""Fetch the P7.3 cross-encoder reranker model files from the Hub.

Stdlib only, so CI jobs without a Python environment can run it with the
system python3. Files land under <out>/<model-id>/, mirroring the runtime
layout (MODEL_CACHE_DIR/<model-id>/onnx/model_quantized.onnx plus the
tokenizer files). Existing files with a matching sha256 are kept; anything
else is re-fetched. The model is never committed to the repository.
"""

import argparse
import hashlib
import os
import sys
import time
import urllib.request
from pathlib import Path

USER_AGENT = "docmind-reranker/1.0 (research; contact local)"
DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
DEFAULT_ENDPOINT = "https://huggingface.co"

# relpath -> sha256, verified against the Hub files 2026-11-13.
MODEL_FILES = {
    "Xenova/ms-marco-MiniLM-L-6-v2": {
        "onnx/model_quantized.onnx": (
            "e9d8ebf845c413e981c175bfe49a3bfa9b3dcce2a3ba54875ee5df5a58639fbe"
        ),
        "tokenizer.json": ("d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"),
        "tokenizer_config.json": (
            "0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53"
        ),
        "config.json": "d827779a72d27ae68cf878a6fc2e954542663fe21ca515d9f4783fc96be2d37e",
    }
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, path: Path, expected: str) -> None:
    if path.is_file() and sha256(path) == expected:
        print(f"cached {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    delays = (2, 5, 10)
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
            if sha256(part) != expected:
                raise ValueError("sha256 mismatch")
            part.replace(path)
            print(f"fetched {path.name}")
            return
        except Exception as exc:
            part.unlink(missing_ok=True)
            if attempt == len(delays):
                raise SystemExit(f"failed to fetch {url}: {type(exc).__name__}") from exc
            time.sleep(delays[attempt])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", required=True)
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT))
    args = parser.parse_args(argv)
    files = MODEL_FILES.get(args.model)
    if files is None:
        raise SystemExit(f"unknown reranker model {args.model}")
    out_dir = Path(args.out) / args.model
    for relpath, expected in files.items():
        url = f"{args.endpoint.rstrip('/')}/{args.model}/resolve/main/{relpath}"
        fetch(url, out_dir / relpath, expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
