import argparse
import json
import operator
import os
import sys
from pathlib import Path

OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "==": operator.eq}


def _value(results: dict, metric: str):
    if metric in results.get("metrics", {}):
        return results["metrics"][metric]
    node = results
    for part in metric.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _fmt(value, gate) -> str:
    if gate.get("of") is not None and isinstance(value, (int, float)):
        return f"{value:g} / {gate['of']}"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--gates", default=str(Path(__file__).with_name("gates.json")))
    parser.add_argument("--markdown-out", default=None)
    args = parser.parse_args(argv)
    gates_doc = json.loads(Path(args.gates).read_text(encoding="utf-8"))
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    rows = []
    failed = False
    for name, gate in gates_doc["gates"].items():
        if gate.get("stage") != args.stage:
            continue
        value = _value(results, gate["metric"])
        threshold = gate["value"]
        if value is None:
            ok = False
        else:
            ok = OPS[gate["op"]](value, threshold)
        if gate.get("gating") and not ok:
            failed = True
        rows.append(
            (
                name,
                _fmt(value, gate),
                f"{gate['op']} {threshold}",
                "PASS" if ok else "FAIL",
                "yes" if gate.get("gating") else "no",
            )
        )
    lines = [
        "| gate | measured | threshold | result | gating |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |" for row in rows]
    table = "\n".join(lines)
    print(table)
    if args.markdown_out:
        out = Path(args.markdown_out)
        out.write_text(table + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("\n" + table + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
