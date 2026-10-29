from docmind_service.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.default_mode == "single"
    assert settings.max_upload_mb == 10
    assert settings.max_pages == 200


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("DOCMIND_MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("DOCMIND_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    assert settings.max_upload_mb == 5
    assert settings.environment == "test"
