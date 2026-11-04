"""Best-effort PII redaction for the public-demo query log (M6.6)."""

from __future__ import annotations

import re

MAX_REDACTED_CHARS = 500

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CHINESE_ID = re.compile(r"\b\d{17}[\dXx]\b")
_CNIC = re.compile(r"\b\d{5}-?\d{7}-?\d\b")
_DIGITS = re.compile(r"(?<![\w+])\+?\d(?:[ \-.()]*\d){7,}(?![\w])")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_SECRET = re.compile(
    r"\b(?:gsk_|sk-|ghp_|tvly-|AIza|dm_)[A-Za-z0-9_\-]{8,}|"
    r"\b[A-Za-z0-9+/_-]{32,}={0,2}\b"
)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

COUNTS = ("email", "id", "card", "phone", "number", "url", "secret", "ip")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _sub(pattern: re.Pattern, text: str, tag: str, counts: dict) -> str:
    def replace(_match) -> str:
        counts[tag] += 1
        return f"[{tag.upper()}]"

    return pattern.sub(replace, text)


def _sub_digits(text: str, counts: dict) -> str:
    def replace(match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        size = len(digits)
        if 13 <= size <= 19 and _luhn_ok(digits):
            tag = "card"
        elif 8 <= size <= 15:
            tag = "phone"
        elif size >= 9:
            tag = "number"
        else:
            return match.group(0)
        counts[tag] += 1
        return f"[{tag.upper()}]"

    return _DIGITS.sub(replace, text)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return the redacted text (at most 500 chars) and per-kind replacement counts."""
    counts = dict.fromkeys(COUNTS, 0)
    clean = _sub(_EMAIL, text, "email", counts)
    clean = _sub(_CHINESE_ID, clean, "id", counts)
    clean = _sub(_CNIC, clean, "id", counts)
    # Run URLs and IPv4 before the generic digit run so their digits are not
    # reclassified as phone/card/number.
    clean = _sub(_IPV4, clean, "ip", counts)
    clean = _sub(_URL, clean, "url", counts)
    clean = _sub(_SECRET, clean, "secret", counts)
    clean = _sub_digits(clean, counts)
    return clean[:MAX_REDACTED_CHARS], counts
