"""Provenance: copied from Project 6 DocMind Agent `evaluation/scoring.py`
at commit 2a91d77f46dd2bab46c5784b28b9e97b5d584f87. Do not improve the scorer here.

Pure scoring functions for the comparison. No network, no LLM. Raw outputs are stored separately,
so scoring can be corrected and rerun without spending tokens."""

import re
import unicodedata

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_DASHES = {ord(c): "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"}
_SPACES = {ord(c): " " for c in "\u00a0\u2002\u2003\u2009\u200a\u202f\u205f\u3000"}
_QUOTES = {ord("\u2018"): "'", ord("\u2019"): "'", ord("\u201c"): '"', ord("\u201d"): '"'}
_ZERO_WIDTH = {ord(c): None for c in "\u200b\u200c\u200d\u2060\ufeff"}
_THOUSANDS_RE = re.compile(r"(?<![\d.])(\d{1,3})[ ,](?=\d{3}(?!\d))")

ABSTAIN_PATTERNS = [
    r"(does\s*not|doesn't|did\s*not|didn't|do\s*not|don't)\s*(contain|mention|provide|include|report|specify|state|cover|discuss|address|give|have|say|offer|present)",
    r"\bnot\s*(mentioned|provided|reported|specified|stated|covered|discussed|addressed|included|found|available|present|given)\b",
    r"\bno\s*(information|mention|data|evidence|details|reference|record)\b",
    r"\b(cannot|can't|can\s*not|unable\s*to)\s*(find|answer|determine|locate|confirm)",
    r"\b(isn't|is\s*not|wasn't|was\s*not|aren't|are\s*not)\s*(mentioned|provided|reported|specified|stated|covered|discussed|included|available|present|given)",
    r"\b(not|n't)\s*(in|within)\s*the\s*(provided\s*|given\s*)?(context|document|paper|text|excerpt)",
]


def clean(text: str) -> str:
    """Normalize typography so equivalent characters compare equal (applied to every system alike)."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _THINK_RE.sub("", text)
    text = text.translate(_ZERO_WIDTH).translate(_DASHES).translate(_SPACES).translate(_QUOTES)
    text = _THOUSANDS_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def score_key_facts(answer: str, key_facts: list) -> dict:
    """Per-fact hits for an answer to an answerable question."""
    cleaned = clean(answer)
    hits = [bool(re.search(kf["answer_regex"], cleaned, re.IGNORECASE)) for kf in key_facts]
    return {"hits": hits, "found": sum(hits), "total": len(hits), "all_found": all(hits)}


def is_abstention(answer: str) -> bool:
    """True if the answer says the information is not available or not in the document."""
    cleaned = clean(answer)
    return any(re.search(p, cleaned, re.IGNORECASE) for p in ABSTAIN_PATTERNS)
