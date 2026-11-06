"""Held-out manifest for Project 9 (Master Script 10.4).

Selects 24 arXiv papers submitted on or after 2026-01-01 (8 per primary
category cs.CL, cs.IR, cs.LG) by a fixed, non-cherry-picked procedure: the
arXiv API is queried per category sorted by submission date ascending, and
the first papers that satisfy the filters (6 to 25 pages, extractable with
pypdf at >= 500 chars per page on average, English) are kept, in order.

PDFs are downloaded only to measure them and are kept under the git-ignored
reports/ tree; only metadata is committed, in evaluation/heldout/manifest.json.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "evaluation" / "heldout" / "manifest.json"
PDF_DIR = ROOT / "reports" / "heldout-pdfs"
CATEGORIES = ["cs.CL", "cs.IR", "cs.LG"]
PER_CATEGORY = 8
MIN_PAGES, MAX_PAGES = 6, 25
MIN_CHARS_PER_PAGE = 500
USER_AGENT = "docmind-heldout/1.0 (research; contact local)"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

MODEL_CUTOFF = {
    "model": "openai/gpt-oss-120b",
    "documented_knowledge_cutoff": "2024-06",
    "source": "OpenAI gpt-oss model card (knowledge cutoff June 2024)",
    "recorded_at": "2026-11-06",
    "note": "All selected papers were submitted on or after 2026-01-01, "
    "far after the documented cutoff.",
}


def get(url: str, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def api_query(category: str) -> tuple[str, list[dict]]:
    query = f"cat:{category} AND submittedDate:[202601010000 TO 202612312359]"
    url = (
        "http://export.arxiv.org/api/query?search_query="
        + urllib.request.quote(query)
        + "&start=0&max_results=120&sortBy=submittedDate&sortOrder=ascending"
    )
    root = ET.fromstring(get(url))
    entries = []
    for entry in root.findall("atom:entry", NS):
        raw_id = entry.findtext("atom:id", "", NS).rsplit("/abs/", 1)[-1]
        match = re.match(r"(.+?)v(\d+)$", raw_id)
        primary = entry.find("arxiv:primary_category", NS)
        entries.append(
            {
                "arxiv_id": match.group(1) if match else raw_id,
                "version": int(match.group(2)) if match else 1,
                "title": " ".join(entry.findtext("atom:title", "", NS).split()),
                "submitted": entry.findtext("atom:published", "", NS)[:10],
                "primary_category": primary.get("term") if primary is not None else "",
                "summary": entry.findtext("atom:summary", "", NS),
            }
        )
    return url, entries


def is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for c in letters if ord(c) < 128)
    return ascii_letters / len(letters) > 0.9


LICENSE_PATTERNS = [
    r"arXiv\.org perpetual, non-exclusive license to distribute",
    r"Creative Commons Attribution[^<]{0,40}",
    r"CC BY[^<]{0,30}",
    r"CC BY-SA[^<]{0,30}",
    r"CC BY-NC-SA[^<]{0,30}",
    r"public domain",
]


LICENSE_LINKS = [
    ("creativecommons.org/licenses/by-nc-sa/4.0", "CC BY-NC-SA 4.0"),
    ("creativecommons.org/licenses/by-sa/4.0", "CC BY-SA 4.0"),
    ("creativecommons.org/licenses/by-nc-nd/4.0", "CC BY-NC-ND 4.0"),
    ("creativecommons.org/licenses/by-nd/4.0", "CC BY-ND 4.0"),
    ("creativecommons.org/licenses/by/4.0", "CC BY 4.0"),
    ("creativecommons.org/publicdomain/zero/1.0", "CC0 1.0"),
    ("licenses/nonexclusive-distrib", "arXiv.org perpetual, non-exclusive license"),
]


def fetch_license(arxiv_id: str) -> str:
    html = get(f"https://arxiv.org/abs/{arxiv_id}").decode("utf-8", "replace")
    for needle, label in LICENSE_LINKS:
        if needle in html:
            return label
    for pattern in LICENSE_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return " ".join(match.group(0).split())
    return "not stated on the abstract page"


def measure_pdf(arxiv_id: str) -> tuple[bytes, int, int]:
    data = get(f"https://arxiv.org/pdf/{arxiv_id}")
    reader = PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    chars = 0
    for page in reader.pages:
        chars += len(page.extract_text() or "")
    return data, pages, chars


def main() -> int:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    papers: list[dict] = []
    queries: dict[str, str] = {}
    for category in CATEGORIES:
        url, entries = api_query(category)
        queries[category] = url
        kept = 0
        for entry in entries:
            if kept >= PER_CATEGORY:
                break
            if entry["primary_category"] != category:
                continue
            if not is_english(entry["title"] + " " + entry["summary"]):
                continue
            try:
                data, pages, chars = measure_pdf(entry["arxiv_id"])
            except Exception as exc:
                print(f"skip {entry['arxiv_id']}: {type(exc).__name__}")
                continue
            if not (MIN_PAGES <= pages <= MAX_PAGES):
                continue
            if chars / pages < MIN_CHARS_PER_PAGE:
                continue
            (PDF_DIR / f"{entry['arxiv_id']}.pdf").write_bytes(data)
            papers.append(
                {
                    "arxiv_id": entry["arxiv_id"],
                    "version": entry["version"],
                    "title": entry["title"],
                    "submitted": entry["submitted"],
                    "primary_category": category,
                    "license": fetch_license(entry["arxiv_id"]),
                    "pdf_url": f"https://arxiv.org/pdf/{entry['arxiv_id']}",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "pages": pages,
                    "extractable_chars": chars,
                    "downloaded_at": datetime.now(UTC).isoformat(),
                }
            )
            kept += 1
            print(f"kept {category} {kept}/{PER_CATEGORY}: {entry['arxiv_id']}")
            time.sleep(3)
        if kept < PER_CATEGORY:
            print(f"WARNING: only {kept} papers for {category}")
        time.sleep(3)
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "procedure": "arXiv API per category, submittedDate from 2026-01-01, "
        "sorted by submission date ascending; first papers passing the filters "
        "(primary category match, English, 6-25 pages, >= 500 extractable "
        "chars per page with pypdf) kept in order; 8 per category.",
        "queries": queries,
        "model_cutoff": MODEL_CUTOFF,
        "count": len(papers),
        "papers": papers,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest written: {len(papers)} papers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
