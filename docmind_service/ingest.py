import hashlib
import io
from dataclasses import dataclass

from pypdf import PdfReader

from docmind_service.chunking import Chunk, chunk_pages


class IngestError(Exception):
    """A safe, user-facing upload error; the library's exception text is never exposed."""

    CODES = {"not_pdf", "encrypted", "too_many_pages", "no_text", "corrupt", "too_large"}

    def __init__(self, code: str, message: str):
        if code not in self.CODES:
            raise ValueError(f"unknown ingest error code: {code}")
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedDocument:
    sha256: str
    pages: list[str]
    chunks: list[Chunk]


def extract_pages(data: bytes, *, max_pages: int) -> list[str]:
    if not data.startswith(b"%PDF-"):
        raise IngestError("not_pdf", "The upload is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IngestError("encrypted", "Encrypted PDFs are not supported.")
        page_count = len(reader.pages)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError("corrupt", "The PDF could not be read.") from exc
    if page_count > max_pages:
        raise IngestError("too_many_pages", f"The PDF has more than {max_pages} pages.")
    pages: list[str] = []
    try:
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except Exception as exc:
        raise IngestError("corrupt", "The PDF could not be read.") from exc
    if not pages or sum(len(page) for page in pages) / len(pages) < 50:
        raise IngestError(
            "no_text", "The PDF has no extractable text; scanned PDFs are not supported."
        )
    return pages


def prepare_document(data: bytes, filename: str, *, max_pages: int) -> PreparedDocument:
    pages = extract_pages(data, max_pages=max_pages)
    return PreparedDocument(
        sha256=hashlib.sha256(data).hexdigest(),
        pages=pages,
        chunks=chunk_pages(pages),
    )
