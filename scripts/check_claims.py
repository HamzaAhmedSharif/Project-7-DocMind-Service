"""Claims check (Master Script 10.6, policy in 3.9).

Scans README.md and docs/*.md for phrases the claims policy forbids:
unqualified superlatives and safety words, "scalable" without a number on the
same line, and "deployed" in a file that carries no link to a green
release-verification (G8) run. Exits 1 and prints every hit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    ("production-grade", re.compile(r"production-grade", re.IGNORECASE)),
    ("enterprise-grade", re.compile(r"enterprise-grade", re.IGNORECASE)),
    ("state-of-the-art", re.compile(r"state-of-the-art", re.IGNORECASE)),
    ("secure (unqualified)", re.compile(r"\bsecure\b", re.IGNORECASE)),
    # "URL-safe" is a character-encoding term, not a safety claim.
    ("safe (unqualified)", re.compile(r"(?<!URL-)\bsafe\b", re.IGNORECASE)),
]
SCALABLE = re.compile(r"\bscalable\b", re.IGNORECASE)
DIGIT = re.compile(r"\d")
DEPLOYED = re.compile(r"\bdeployed\b", re.IGNORECASE)
G8_LINK = "actions/runs/"


IGNORE_START = "<!-- claims-check-ignore-start -->"
IGNORE_END = "<!-- claims-check-ignore-end -->"


def strip_ignored(text: str) -> str:
    """Blank out regions that quote the forbidden phrases in order to forbid
    them (the claims list in docs/FACTS.md), preserving line numbers."""
    lines = text.splitlines()
    inside = False
    for index, line in enumerate(lines):
        if IGNORE_START in line:
            inside = True
        if inside:
            lines[index] = ""
        if IGNORE_END in line:
            inside = False
    return "\n".join(lines)


def check_text(text: str) -> list[str]:
    text = strip_ignored(text)
    hits: list[str] = []
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"{label} at line {line}")
    for number, line in enumerate(text.splitlines(), start=1):
        if SCALABLE.search(line) and not DIGIT.search(line):
            hits.append(f"scalable without a number at line {number}")
    if DEPLOYED.search(text) and G8_LINK not in text:
        hits.append("deployed without a release-verification run link in the same file")
    return hits


def target_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(sorted((ROOT / "docs").glob("*.md")))
    return [path for path in files if path.is_file()]


def main() -> int:
    failed = False
    for path in target_files():
        hits = check_text(path.read_text(encoding="utf-8"))
        for hit in hits:
            print(f"{path.relative_to(ROOT)}: {hit}")
            failed = True
    if failed:
        return 1
    print("claims check clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
