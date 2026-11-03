from fastapi.testclient import TestClient

from docmind_service.main import app

client = TestClient(app)


def test_document_routes_without_a_store_are_problem_json():
    for method, path, kwargs in [
        ("post", "/v1/documents", {"files": {"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}}),
        ("get", "/v1/documents", {}),
        ("delete", "/v1/documents/3f6c1e2a-9b7d-4c1e-8a55-0d2f4b6e7a10", {}),
    ]:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 501
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["status"] == 501


def test_validation_errors_are_problem_json():
    response = client.post("/v1/query", json={"question": ""})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "question" in response.json()["detail"]


def test_unknown_routes_are_problem_json():
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
