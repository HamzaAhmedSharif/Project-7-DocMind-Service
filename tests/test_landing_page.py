import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from docmind_service.config import Settings
from docmind_service.main import create_app
from scripts.make_tiny_pdf import make_pdf
from scripts.smoke_http import multipart

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    return TestClient(create_app(settings=Settings(_env_file=None)))


def test_landing_page_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_static_app_js_is_served(client):
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "content-security-policy" in response.headers


def test_app_js_has_no_html_sinks():
    text = (ROOT / "docmind_service" / "static" / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", text)


def test_sample_questions_match_the_manifest():
    text = (ROOT / "docmind_service" / "static" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"const SAMPLE_QUESTIONS = (\[.*?\]);", text, re.DOTALL)
    assert match
    expected = json.loads((ROOT / "evaluation" / "demo_questions.json").read_text(encoding="utf-8"))
    assert json.loads(match.group(1)) == [item["question"] for item in expected["questions"]]


def test_page_text_mentions_limits_and_privacy():
    html = (ROOT / "docmind_service" / "static" / "index.html").read_text(encoding="utf-8")
    assert "5 questions per minute" in html
    assert "300 questions per day" in html
    assert "Questions asked here are stored for 30 days" in html
    assert "Do not enter personal data." in html


def test_uploads_disabled_returns_403():
    client = TestClient(create_app(settings=Settings(_env_file=None, uploads_enabled=False)))
    body, ctype = multipart("t.pdf", make_pdf(["some text"]))
    response = client.post("/v1/documents", content=body, headers={"content-type": ctype})
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert client.delete(f"/v1/documents/{uuid4()}").status_code == 403


def test_per_ip_limit_returns_429_with_retry_after():
    client = TestClient(create_app(settings=Settings(_env_file=None, demo_ip_per_min=1)))
    first = client.post("/v1/query", json={"question": "What is self-attention?"})
    assert first.status_code == 200
    second = client.post("/v1/query", json={"question": "What is self-attention?"})
    assert second.status_code == 429
    assert second.headers["content-type"].startswith("application/problem+json")
    assert int(second.headers["retry-after"]) >= 1


def test_daily_cap_returns_429():
    client = TestClient(create_app(settings=Settings(_env_file=None, demo_daily_cap=0)))
    response = client.post("/v1/query", json={"question": "What is self-attention?"})
    assert response.status_code == 429
    assert "daily" in response.json()["detail"].lower()
