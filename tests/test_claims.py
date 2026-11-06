"""The claims check (Master Script 10.6): the matcher catches the forbidden
phrases of the claims policy, and the repository's own documents stay clean."""

from scripts.check_claims import check_text, target_files


def test_forbidden_phrases_are_caught():
    assert check_text("A production-grade service.") != []
    assert check_text("An enterprise-grade platform.") != []
    assert check_text("State-of-the-art retrieval.") != []
    assert check_text("The service is secure.") != []
    assert check_text("Your data is safe.") != []


def test_scalable_needs_a_number():
    assert check_text("It is scalable.") != []
    assert check_text("It is scalable to 100 queries per minute.") == []


def test_deployed_needs_a_run_link():
    assert check_text("The service is deployed.") != []
    ok = "The service is deployed. Run: https://github.com/x/y/actions/runs/123"
    assert check_text(ok) == []


def test_plain_factual_text_is_clean():
    text = "A production-style RAG service on free tiers, measured locally."
    assert check_text(text) == []


def test_url_safe_is_an_encoding_term_not_a_claim():
    assert check_text("The random part is 32 URL-safe characters.") == []


def test_ignored_region_may_quote_forbidden_phrases():
    text = (
        "Forbidden:\n<!-- claims-check-ignore-start -->\n"
        '- "production-grade", "secure", "safe"\n'
        "<!-- claims-check-ignore-end -->\nClean prose."
    )
    assert check_text(text) == []
    assert check_text("production-grade, outside any ignore region.") != []


def test_repository_documents_are_clean():
    failures = {}
    for path in target_files():
        hits = check_text(path.read_text(encoding="utf-8"))
        if hits:
            failures[str(path)] = hits
    assert failures == {}
