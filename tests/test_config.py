from docmind_service.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.default_mode == "single"
    assert settings.default_top_k == 10
    assert settings.max_upload_mb == 10
    assert settings.max_pages == 200
    assert settings.auto_migrate is False
    assert settings.llm_provider == "fake"
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.hosted_rpm == 20
    assert settings.hosted_tpm == 8000
    assert settings.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.reranker_enabled is True
    assert settings.reranker_model == "Xenova/ms-marco-MiniLM-L-6-v2"
    assert settings.rerank_candidates == 25


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("DOCMIND_MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("DOCMIND_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    assert settings.max_upload_mb == 5
    assert settings.environment == "test"


def test_secret_values_are_not_in_the_settings_string(monkeypatch):
    monkeypatch.setenv("DOCMIND_LLM_API_KEY", "UNIQUE-SECRET-12345")
    monkeypatch.setenv("DOCMIND_DATABASE_URL", "postgresql://user:UNIQUE-SECRET-12345@db/x")
    settings = Settings(_env_file=None)
    assert settings.llm_api_key_value == "UNIQUE-SECRET-12345"
    assert "UNIQUE-SECRET-12345" not in str(settings)
    assert "UNIQUE-SECRET-12345" not in repr(settings)


def test_empty_git_sha_reads_as_no_commit(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert Settings(_env_file=None, git_sha="").commit_sha is None
    assert Settings(_env_file=None, git_sha="   ").commit_sha is None
    assert Settings(_env_file=None, git_sha="deadbeef").commit_sha == "deadbeef"
