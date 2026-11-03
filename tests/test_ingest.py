import hashlib

import pytest
from pypdf import PdfWriter

from docmind_service.ingest import IngestError, extract_pages, prepare_document
from scripts.make_tiny_pdf import make_pdf

LONG = "This page contains enough text to pass the extraction check. " * 3


def test_valid_pdf_round_trips_pages():
    data = make_pdf([LONG, LONG + "Second page."])
    pages = extract_pages(data, max_pages=10)
    assert len(pages) == 2
    assert "This page contains" in pages[0]
    assert "Second page" in pages[1]


def test_non_pdf_is_rejected():
    with pytest.raises(IngestError) as info:
        extract_pages(b"not a pdf", max_pages=10)
    assert info.value.code == "not_pdf"


def test_encrypted_pdf_is_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    import io

    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(IngestError) as info:
        extract_pages(data.getvalue(), max_pages=10)
    assert info.value.code == "encrypted"


def test_page_limit_is_enforced_before_extraction():
    data = make_pdf([LONG, LONG])
    with pytest.raises(IngestError) as info:
        extract_pages(data, max_pages=1)
    assert info.value.code == "too_many_pages"
    assert "1" in str(info.value)


def test_pdf_without_text_is_rejected():
    with pytest.raises(IngestError) as info:
        extract_pages(make_pdf(["", ""]), max_pages=10)
    assert info.value.code == "no_text"


def test_corrupt_pdf_is_rejected_without_library_text():
    with pytest.raises(IngestError) as info:
        extract_pages(b"%PDF-1.4\nnot a real pdf body", max_pages=10)
    assert info.value.code == "corrupt"
    assert "not a real pdf body" not in str(info.value)


def test_prepare_document_has_a_stable_hash_pages_and_chunks():
    data = make_pdf([LONG, LONG])
    first = prepare_document(data, "paper.pdf", max_pages=10)
    again = prepare_document(data, "renamed.pdf", max_pages=10)
    assert first.sha256 == hashlib.sha256(data).hexdigest()
    assert first.sha256 == again.sha256
    assert len(first.pages) == 2
    assert first.chunks
    assert first.chunks[0].page == 1
