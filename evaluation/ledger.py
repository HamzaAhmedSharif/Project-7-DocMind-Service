"""Provider-call ledger (Master Script 10.1).

Append-only CSV at reports/provider-ledger.csv (the reports/ tree is git-ignored).
Every script that calls the provider records the adapter's call-count delta here so
the combined daily cap of 800 can be pre-flighted by scripts/provider_budget.py.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "reports" / "provider-ledger.csv"


def record(activity: str, n: int, *, path: Path = LEDGER_PATH) -> None:
    if n <= 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["date_utc", "activity", "n"])
        writer.writerow([datetime.now(UTC).date().isoformat(), activity, int(n)])


def used_today(*, path: Path = LEDGER_PATH) -> int:
    if not path.is_file():
        return 0
    today = datetime.now(UTC).date().isoformat()
    total = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("date_utc") == today:
                total += int(row.get("n") or 0)
    return total


if __name__ == "__main__":
    print(f"used_today={used_today()}")
