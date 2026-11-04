from uuid import uuid4

import pytest

from docmind_service.domain import RetrievedChunk
from evaluation.calibrate_evidence import _top1, threshold_from
from evaluation.no_citation import summarize


def test_threshold_rule_is_floor_of_min_minus_two_hundredths():
    assert threshold_from([0.31, 0.40]) == 0.29
    assert threshold_from([0.20]) == 0.18
    assert threshold_from([0.305]) == 0.28
    assert threshold_from([0.01]) == 0.0
    with pytest.raises(ValueError):
        threshold_from([])


class FakeStore:
    def __init__(self, hits):
        self.hits = hits

    def retrieve(self, question, *, tenant_id, document_ids, top_k):
        return self.hits


def test_top1_returns_the_score_and_page_or_zero_when_empty():
    chunk = RetrievedChunk(
        chunk_id="d:3",
        document_id=uuid4(),
        page=7,
        text="x",
        score=0.456789,
    )
    row = _top1(FakeStore([chunk]), "question", "tenant")
    assert row == {"score": 0.456789, "chunk_id": "d:3", "page": 7}
    assert _top1(FakeStore([]), "question", "tenant") == {
        "score": 0.0,
        "chunk_id": None,
        "page": None,
    }


def test_no_citation_summary_counts_only_non_refused_answers():
    rows = [
        {"refused": False, "citations": 0},
        {"refused": False, "citations": 2},
        {"refused": True, "citations": 0},
        {"refused": False, "citations": 0},
    ]
    summary = summarize(rows)
    assert summary == {"total": 4, "no_citation": 2, "recommended_default": False}


def test_no_citation_summary_recommends_true_at_one_or_zero():
    assert summarize([{"refused": False, "citations": 0}])["recommended_default"] is True
    assert summarize([{"refused": False, "citations": 1}])["recommended_default"] is True
