import re
from dataclasses import dataclass

CHUNK_WORDS = 800
CHUNK_OVERLAP = 25
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page: int
    text: str


def chunk_pages(
    pages: list[str], *, words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    """One word stream for the whole document; a chunk's page is the page of its first word."""
    if words <= overlap or overlap < 0:
        raise ValueError("need words > overlap >= 0")
    stream = [(w, n) for n, text in enumerate(pages, start=1) for w in _WS.sub(" ", text).split()]
    chunks, start, step = [], 0, words - overlap
    while start < len(stream):
        window = stream[start : start + words]
        chunks.append(Chunk(len(chunks), window[0][1], " ".join(w for w, _ in window)))
        if start + words >= len(stream):
            break
        start += step
    return chunks
