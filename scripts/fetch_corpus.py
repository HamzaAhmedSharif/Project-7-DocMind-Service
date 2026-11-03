"""Fetch corpus PDFs by manifest hash. The PDF is never committed or printed."""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

USER_AGENT = "docmind-corpus/1.0 (research; contact local)"


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
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    for item in manifest["corpora"]:
        fetch(item["url"], out_dir / f"{item['id']}.pdf", item["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
