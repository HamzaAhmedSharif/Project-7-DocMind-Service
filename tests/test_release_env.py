from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = {"DATABASE_URL", "DATABASE_URL_DIRECT", "LLM_API_KEY", "METRICS_TOKEN"}


def test_release_env_is_non_secret_and_has_the_expected_keys():
    lines = [
        line.strip()
        for line in (ROOT / "deploy" / "release.env").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    names = [line.split("=", 1)[0] for line in lines]
    assert all(name.startswith("DOCMIND_") for name in names)
    assert all("=" in line and line.split("=", 1)[1] for line in lines)
    assert not ({name.removeprefix("DOCMIND_") for name in names} & SECRET_NAMES)
    assert names == [
        "DOCMIND_ENVIRONMENT",
        "DOCMIND_LLM_PROVIDER",
        "DOCMIND_UPLOADS_ENABLED",
        "DOCMIND_AUTO_MIGRATE",
        "DOCMIND_TRUST_PROXY_HOPS",
        "DOCMIND_LOG_LEVEL",
        "DOCMIND_DEMO_DAILY_CAP",
        "DOCMIND_DEMO_IP_PER_MIN",
    ]
