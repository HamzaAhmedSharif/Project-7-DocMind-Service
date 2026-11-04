import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_has_real_hashes_and_the_page_budget():
    data = json.loads((ROOT / "evaluation" / "demo_corpus.json").read_text(encoding="utf-8"))
    corpora = data["corpora"]
    assert 3 <= len(corpora) <= 5
    total_pages = 0
    for item in corpora:
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert item["pages"] > 0
        assert item["license_url"].startswith("https://")
        total_pages += item["pages"]
    assert 100 <= total_pages <= 300


def test_questions_are_six_and_unique():
    data = json.loads((ROOT / "evaluation" / "demo_questions.json").read_text(encoding="utf-8"))
    questions = data["questions"]
    assert len(questions) == 6
    assert len({item["id"] for item in questions}) == 6
    assert all(item["question"].strip() for item in questions)
