from fastapi.testclient import TestClient

from docmind_service import __version__
from docmind_service.main import app

client = TestClient(app)


def test_healthz_is_ok_and_reports_version_and_commit():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "commit": None}


def test_healthz_empty_git_sha_is_null(monkeypatch):
    from docmind_service.config import Settings
    from docmind_service.main import create_app

    monkeypatch.setenv("DOCMIND_GIT_SHA", "")
    empty = TestClient(create_app(settings=Settings(_env_file=None)))
    assert empty.get("/healthz").json()["commit"] is None


def test_readyz_is_demo_ready_without_a_database():
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ready",
        "checks": {"database": "demo", "embedder": "demo", "provider": "demo"},
    }
