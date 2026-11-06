"""The README gate table is generated from the committed result files
(Master Script 10.6); this test fails when the committed block drifts."""

from pathlib import Path

from scripts.sync_readme import BEGIN, END, generate_block

ROOT = Path(__file__).resolve().parent.parent


def test_readme_gate_table_is_in_sync():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert BEGIN in text and END in text
    _, rest = text.split(BEGIN, 1)
    committed, _ = rest.split(END, 1)
    generated = generate_block()
    _, generated_rest = generated.split(BEGIN, 1)
    generated_block, _ = generated_rest.split(END, 1)
    assert committed.strip() == generated_block.strip()
