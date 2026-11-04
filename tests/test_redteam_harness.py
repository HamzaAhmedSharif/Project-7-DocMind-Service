import hashlib
import json
from pathlib import Path

from docmind_service.config import Settings
from docmind_service.fakes import ScriptedLLM
from docmind_service.guardrails import RULES
from docmind_service.query import PROMPT_TEMPLATE
from evaluation.redteam import run_redteam as redteam

CASES = json.loads((Path(redteam.__file__).with_name("cases.json")).read_text(encoding="utf-8"))[
    "cases"
]
CASE = {case["id"]: case for case in CASES}


def test_placeholders_resolve_per_arm():
    assert redteam.resolve("{PREAMBLE}", "on", "C").startswith(RULES[:60])
    assert redteam.resolve("{PREAMBLE}", "off", "C").startswith(PROMPT_TEMPLATE[:60])
    assert redteam.resolve("{CANARY}", "on", "C") == "C"
    assert redteam.resolve("{CANARY}", "off", "C") == "NO-CANARY"


def test_classify_is_case_insensitive_and_reports_both_directions():
    assert redteam.classify("the marker is PWNED-01", ["PWNED-01"]) is True
    assert redteam.classify("pwned-01", ["PWNED-01"]) is True
    assert redteam.classify("the door is green", ["PWNED-01"]) is False


def test_split_passage_splits_the_two_chunk_case():
    assert len(redteam.split_passage(CASE["15"]["passage"])) == 2


def test_a_resistant_model_is_classified_as_not_hit():
    llm = redteam.RecordingLLM(redteam.DryRunLLM())
    record = redteam.run_case(
        CASE["01"],
        arm="on",
        repeat=0,
        llm=llm,
        canary="TEST-CANARY",
        base_settings=Settings(_env_file=None),
    )
    assert record["raw_hit"] is False
    assert record["final_hit"] is False
    assert record["model_resisted"] is True
    assert record["guardrail_caught"] is False


def test_a_compliant_model_is_classified_as_hit():
    llm = redteam.RecordingLLM(ScriptedLLM(["PWNED-01 [c1]"]))
    record = redteam.run_case(
        CASE["01"],
        arm="on",
        repeat=0,
        llm=llm,
        canary="TEST-CANARY",
        base_settings=Settings(_env_file=None),
    )
    assert record["raw_hit"] is True
    assert record["final_hit"] is True
    assert record["model_resisted"] is False
    assert record["guardrail_caught"] is False


def test_a_guardrail_caught_attack_is_raw_hit_but_not_final_hit():
    llm = redteam.RecordingLLM(ScriptedLLM(["[c99] a plain answer"]))
    record = redteam.run_case(
        CASE["06"],
        arm="on",
        repeat=0,
        llm=llm,
        canary="TEST-CANARY",
        base_settings=Settings(_env_file=None),
    )
    assert record["raw_hit"] is True
    assert record["final_hit"] is False
    assert record["guardrail_caught"] is True
    assert record["refusal_reason"] == "ungrounded"


def test_the_off_arm_does_not_remove_the_fake_citation():
    llm = redteam.RecordingLLM(ScriptedLLM(["[c99] a plain answer"]))
    record = redteam.run_case(
        CASE["06"],
        arm="off",
        repeat=0,
        llm=llm,
        canary="TEST-CANARY",
        base_settings=Settings(_env_file=None),
    )
    assert record["raw_hit"] is True
    assert record["final_hit"] is True


def test_dry_run_makes_no_network_call(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("HostedLLM must not be constructed in --dry-run")

    monkeypatch.setattr(redteam, "HostedLLM", boom)
    out = tmp_path / "redteam.json"
    assert redteam.main(["--dry-run", "--out", str(out), "--repeats", "1"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["dry_run"] is True
    assert data["provider_requests_total"] == 0
    assert data["summary"]["on"]["provider_requests"] == 0


def test_result_file_records_the_cases_hash_and_counts(tmp_path):
    out = tmp_path / "redteam.json"
    assert redteam.main(["--dry-run", "--out", str(out), "--repeats", "2"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    cases_path = Path(redteam.__file__).with_name("cases.json")
    expected = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    assert data["cases_hash"] == expected
    assert data["cases_total"] == 15
    assert len(data["records"]) == 15 * 2 * 2
    assert data["summary"]["on"]["cases_total"] == 15
    assert data["summary"]["off"]["cases_total"] == 15
    assert data["r1_attacks_succeeded_guardrails_on"] == 0
    assert data["r1_attacks_succeeded_guardrails_off"] == 0
    for case_id in {record["case_id"] for record in data["records"]}:
        assert len([r for r in data["records"] if r["case_id"] == case_id]) == 4
