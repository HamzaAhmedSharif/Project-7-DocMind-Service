import pytest
from fastapi.testclient import TestClient

from docmind_service.main import app

client = TestClient(app)
PDF = ("sample.pdf", b"%PDF-1.4 minimal", "application/pdf")
DOC_ID = "3f6c1e2a-9b7d-4c1e-8a55-0d2f4b6e7a10"


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/v1/documents", {"files": {"file": PDF}}),
        ("get", "/v1/documents", {}),
        ("delete", f"/v1/documents/{DOC_ID}", {}),
    ],
)
def test_document_routes_are_stubs_that_return_problem_json(method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 501
    assert body["title"] == "Not Implemented"


def test_validation_errors_are_problem_json():
    response = client.post("/v1/query", json={"question": ""})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "question" in response.json()["detail"]


def test_unknown_routes_are_problem_json():
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
