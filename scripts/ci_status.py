"""Print the latest GitHub Actions runs with jobs and failing steps (public API, no token)."""

import json
import sys
import urllib.request

REPO = "HamzaAhmedSharif/Project-7-DocMind-Service"
API = f"https://api.github.com/repos/{REPO}/actions"


def get(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "docmind-ci-status", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main(limit: int = 3) -> None:
    for run in get(f"{API}/runs?per_page={limit}")["workflow_runs"]:
        print(
            f"{run['name']} {run['head_sha'][:7]} {run['status']} "
            f"{run['conclusion']} {run['html_url']}"
        )
        for job in get(f"{API}/runs/{run['id']}/jobs")["jobs"]:
            print(f"  job {job['name']}: {job['status']} {job['conclusion']}")
            for step in job["steps"]:
                if step["conclusion"] not in (None, "success", "skipped"):
                    print(f"    FAILED step: {step['name']} ({step['conclusion']})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
