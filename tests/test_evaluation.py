"""Scoring tests copied from Project 6 at 2a91d77f46dd2bab46c5784b28b9e97b5d584f87."""

import re

import pytest

from evaluation.questions import QUESTIONS
from evaluation.scoring import clean, is_abstention, score_key_facts

QMAP = {q["id"]: q for q in QUESTIONS}


def test_question_set_has_the_expected_shape():
    counts = {}
    for question in QUESTIONS:
        counts[question["type"]] = counts.get(question["type"], 0) + 1
    assert counts == {"doc": 12, "web": 4, "absent": 4}
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)
    assert all(q["expected_route"] == "WEB" for q in QUESTIONS if q["type"] == "web")


def test_every_pattern_compiles():
    for question in QUESTIONS:
        for fact in question.get("key_facts", []):
            re.compile(fact["answer_regex"])
            re.compile(fact["paper_regex"])
        for pattern in question.get("absent_regex", []):
            re.compile(pattern)


def test_clean_normalizes_typography():
    assert clean("Scaled Dot\u2011Product") == "Scaled Dot-Product"
    assert clean("warm\u2011up of 4\u202f000 steps") == "warm-up of 4000 steps"
    assert clean("it\u2019s") == "it's"


def test_thousands_separators_are_not_applied_to_unrelated_numbers():
    assert clean("28.4, 41.8 and 512 2048") == "28.4, 41.8 and 512 2048"


def test_score_key_facts_counts_matches_after_normalization():
    answer = "Scaled Dot\u2011Product Attention applies a softmax after dividing by sqrt(d_k)."
    result = score_key_facts(answer, QMAP["d02"]["key_facts"])
    assert result["found"] == 3 and result["all_found"] is True


def test_score_key_facts_reports_misses():
    result = score_key_facts("It is a kind of pooling.", QMAP["d02"]["key_facts"])
    assert result["found"] == 0 and result["hits"] == [False, False, False]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The paper does not mention ImageNet.", True),
        ("The paper doesn\u2019t mention ImageNet.", True),
        ("There is no information about this in the provided context.", True),
        ("I cannot answer the question from the given sources.", True),
        ("The Transformer reached 28.4 BLEU.", False),
    ],
)
def test_is_abstention(text, expected):
    assert is_abstention(text) is expected
