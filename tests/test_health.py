from fastapi.testclient import TestClient

from docmind_service import __version__
from docmind_service.main import app

client = TestClient(app)


def test_healthz_is_ok_and_reports_version_and_commit():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "commit": None}


def test_readyz_is_demo_ready_without_a_database():
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ready",
        "checks": {"database": "demo", "embedder": "demo", "provider": "demo"},
    }
