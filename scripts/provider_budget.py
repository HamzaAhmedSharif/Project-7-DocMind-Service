"""Provider budget ledger: local calls plus today's release-smoke runs (upper bound)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = "HamzaAhmedSharif/Project-7-DocMind-Service"
WORKFLOW = "release-smoke.yml"


def release_smoke_runs(repo: str, workflow: str, day: str) -> int:
    query = urllib.parse.urlencode({"created": f">={day}", "per_page": 100})
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?{query}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "docmind-budget"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    return sum(1 for run in data.get("workflow_runs", []) if run.get("created_at", "")[:10] == day)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count today's provider budget.")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--workflow", default=WORKFLOW)
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--used-today", type=int, default=0)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    try:
        runs = release_smoke_runs(args.repo, args.workflow, args.date)
    except Exception as exc:
        print(f"release-smoke run count unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2

    total = args.used_today + runs
    print(f"date={args.date}")
    print(f"release_smoke_runs_today={runs}")
    print(f"used_today={args.used_today}")
    print(f"used_today_upper_bound={total}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "date": args.date,
                    "release_smoke_runs": runs,
                    "used_today": args.used_today,
                    "used_today_upper_bound": total,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
