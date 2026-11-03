import json
import subprocess
from pathlib import Path

import pytest

from docmind_service.chunking import chunk_pages

P6_REPO = Path(r"A:\HDD\Work\VS Code - Python\GitHub\Project-6-DocMind-Agent")
P6_PYTHON = Path(r"B:\Applications\MiniConda\envs\rag\python.exe")


def test_chunk_size_overlap_and_ordinals():
    words = [f"w{i}" for i in range(300)]
    chunks = chunk_pages([" ".join(words)], words=100, overlap=20)
    assert [len(c.text.split()) for c in chunks] == [100, 100, 100, 60]
    assert [c.ordinal for c in chunks] == [0, 1, 2, 3]
    assert chunks[0].text.split()[0] == "w0"
    assert chunks[0].text.split()[-1] == "w99"
    assert chunks[1].text.split()[0] == "w80"


def test_page_is_the_page_of_the_first_word():
    chunks = chunk_pages(["one two ", "three four five"], words=2, overlap=0)
    assert [(c.page, c.text) for c in chunks] == [
        (1, "one two"),
        (2, "three four"),
        (2, "five"),
    ]


def test_last_partial_window_is_kept():
    chunks = chunk_pages(["a b c d"], words=3, overlap=0)
    assert [c.text for c in chunks] == ["a b c", "d"]


def test_whitespace_is_normalized_and_unicode_is_preserved():
    chunks = chunk_pages(["hello\tworld\n", "こんにちは 世界"], words=2, overlap=0)
    assert [c.text for c in chunks] == ["hello world", "こんにちは 世界"]


def test_empty_pages_return_no_chunks():
    assert chunk_pages([]) == []
    assert chunk_pages(["", "  \n"]) == []


def test_overlap_must_be_smaller_than_words():
    with pytest.raises(ValueError):
        chunk_pages(["one"], words=1, overlap=1)
    with pytest.raises(ValueError):
        chunk_pages(["one"], words=1, overlap=-1)


def test_is_deterministic():
    pages = [f"page {i} " + " ".join(f"w{j}" for j in range(50)) for i in range(5)]
    assert chunk_pages(pages) == chunk_pages(pages)


@pytest.mark.skipif(
    not (P6_REPO / "agents" / "ingest.py").exists() or not P6_PYTHON.exists(),
    reason="Project 6 repo or rag environment absent",
)
def test_matches_p6_chunk_text_on_the_same_word_stream():
    text = " ".join(f"w{i}" for i in range(401))
    code = (
        "import json, sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "from agents.ingest import chunk_text; "
        "print(json.dumps(chunk_text(sys.stdin.read(), 150, 25)))"
    )
    result = subprocess.run(
        [str(P6_PYTHON), "-c", code, str(P6_REPO)],
        input=text,
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    )
    assert [c.text for c in chunk_pages([text])] == json.loads(result.stdout)
