import json
from pathlib import Path

from docmind_service.main import app

CONTRACT = Path(__file__).resolve().parent.parent / "openapi.json"


def load_contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_committed_contract_matches_the_app():
    current = json.loads(json.dumps(app.openapi()))
    assert load_contract() == current, (
        "openapi.json is out of date: run python scripts/export_openapi.py"
    )


def test_contract_declares_the_v1_endpoints():
    paths = load_contract()["paths"]
    assert set(paths) == {
        "/healthz",
        "/readyz",
        "/v1/documents",
        "/v1/documents/{document_id}",
        "/v1/query",
    }
    assert set(paths["/v1/documents"]) == {"get", "post"}
    assert set(paths["/v1/documents/{document_id}"]) == {"delete"}
    assert set(paths["/v1/query"]) == {"post"}


def test_contract_declares_the_api_key_scheme():
    schemes = load_contract()["components"]["securitySchemes"]
    assert any(s.get("name") == "X-API-Key" and s.get("in") == "header" for s in schemes.values())
