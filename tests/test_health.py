from fastapi.testclient import TestClient

from docmind_service.main import app

client = TestClient(app)


def test_healthz_is_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_dependencies_not_configured():
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert set(body["checks"]) == {"database", "embedder", "provider"}
