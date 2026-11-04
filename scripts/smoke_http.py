"""HTTP smoke test for DocMind: standard library only.

Modes:
  ci         - the compose stack, fake provider (M4.3)
  live       - a persistent host (M5.7)
  ephemeral  - the release image, nine checks (A1.4 / G8-C)

Prints `PASS <name>` or `FAIL <name>: <reason>` for every check and exits 1
if any check failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.make_tiny_pdf import make_pdf  # noqa: E402

PDF_TEXT = (
    "Self-attention lets each token weigh every other token. "
    "Positional encodings give order information."
)
NO_EVIDENCE_QUESTION = "zzzz qqqq"
DEMO_DOCUMENT_COUNT = 3


def multipart(filename: str, data: bytes, field: str = "file"):
    boundary = "----docmind" + uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    return (
        head + data + f"\r\n--{boundary}--\r\n".encode(),
        f"multipart/form-data; boundary={boundary}",
    )


def _header(headers: dict, name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def mem_peak_mib(path: str | None) -> float | None:
    """Parse the largest `docker stats` MemUsage value from mem.txt."""
    if not path or not Path(path).is_file():
        return None
    peak = 0.0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"([\d.]+)\s*([KMG]i?B)", line.strip())
        if not match:
            continue
        value, unit = float(match.group(1)), match.group(2).lower()
        peak = max(peak, value * {"kib": 1 / 1024, "mib": 1, "gib": 1024}[unit])
    return round(peak, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocMind HTTP smoke test.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--mode", choices=["ci", "live", "ephemeral"], required=True)
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--expect-commit", default=None)
    parser.add_argument("--expect-image-revision", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--check-limits", action="store_true")
    parser.add_argument("--ip-per-min", type=int, default=5)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--mem-file", default=None)
    parser.add_argument("--runner-type", default="local")
    parser.add_argument("--container-limit", default="512m")
    parser.add_argument(
        "--conditions",
        default="local Docker, 512 MB container limit, local Postgres, hosted provider",
    )
    return parser


class Smoke:
    def __init__(self, base: str, deadline_s: int, api_key: str | None) -> None:
        self.base = base.rstrip("/")
        self.deadline_s = deadline_s
        self.api_key = api_key
        self.ok = True
        self.checks = 0
        self.results: list[dict] = []
        self.info: dict = {}

    def record(self, name: str, passed: bool, reason: str = "") -> None:
        self.checks += 1
        self.results.append({"name": name, "passed": passed, "reason": reason})
        if not passed:
            self.ok = False
            print(f"FAIL {name}: {reason}")
        else:
            print(f"PASS {name}")

    def request(self, method: str, path: str, body=None, headers=None, auth: bool = True):
        headers = dict(headers or {})
        if self.api_key and auth:
            headers["X-API-Key"] = self.api_key
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.deadline_s) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def poll(self, name: str, path: str, until, reason: str) -> None:
        stop = time.monotonic() + self.deadline_s
        status, header, body = None, {}, b""
        while time.monotonic() < stop:
            try:
                status, header, body = self.request("GET", path)
                if until(status, header, body):
                    self.record(name, True)
                    return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(1)
        preview = body[:200].decode("utf-8", "replace") if isinstance(body, bytes) else ""
        self.record(name, False, f"{reason} (last status={status}, body={preview!r})")

    def get_json(self, method: str, path: str, body=None, headers=None, auth: bool = True):
        status, header, raw = self.request(method, path, body, headers, auth)
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            parsed = None
        return status, header, parsed


def run_ci(smoke: Smoke) -> None:
    smoke.poll("/healthz 200", "/healthz", lambda s, h, b: s == 200, "never returned 200")

    def _has_version(s: int, h: dict, b: bytes) -> bool:
        if s != 200:
            return False
        doc = json.loads(b)
        return bool(doc.get("version"))

    smoke.poll("/healthz has version", "/healthz", _has_version, "missing version")
    smoke.poll("/readyz 200", "/readyz", lambda s, h, b: s == 200, "service not ready")

    # --- anonymous upload must return 403 (M6: anonymous cannot write) ---
    pdf = make_pdf([PDF_TEXT])
    body, ctype = multipart("smoke.pdf", pdf)
    status, _, _ = smoke.get_json(
        "POST", "/v1/documents", body, {"Content-Type": ctype}, auth=False
    )
    smoke.record("anonymous upload 403", status == 403, f"status={status}")

    # --- keyed upload / CRUD flow (requires write-scoped key) ---
    body, ctype = multipart("smoke.pdf", pdf)
    status, _, doc = smoke.get_json("POST", "/v1/documents", body, {"Content-Type": ctype})
    same_id = bool(doc) and doc.get("document_id")
    smoke.record(
        "upload 201 pages 1",
        status == 201 and bool(doc) and doc.get("pages") == 1,
        f"status={status} doc={doc}",
    )

    body, ctype = multipart("smoke.pdf", pdf)
    status, _, dup = smoke.get_json("POST", "/v1/documents", body, {"Content-Type": ctype})
    smoke.record(
        "re-upload 200 same id",
        status == 200 and bool(dup) and dup.get("document_id") == same_id,
        f"status={status} doc={dup}",
    )

    status, _, listing = smoke.get_json("GET", "/v1/documents")
    present = bool(listing) and any(
        i.get("document_id") == same_id for i in listing.get("items", [])
    )
    smoke.record(
        "list contains document", status == 200 and present, f"status={status} items={listing}"
    )

    qbody = json.dumps({"question": "What does self-attention do?"}).encode()
    status, header, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    cites_ok = bool(answer) and any(
        c.get("document_id") == same_id and c.get("page") == 1 for c in answer.get("citations", [])
    )
    request_id_ok = bool(answer) and answer.get("request_id") == _header(header, "X-Request-ID")
    smoke.record(
        "query 200 explained",
        status == 200
        and bool(answer)
        and answer.get("refused") is False
        and cites_ok
        and request_id_ok,
        f"status={status} answer={answer} header={_header(header, 'X-Request-ID')}",
    )

    # M6 guardrails filter chunks below the relevance floor, so a filter that
    # matches nothing returns low_evidence; assert the exact M6 reason.
    qbody = json.dumps(
        {"question": NO_EVIDENCE_QUESTION, "document_ids": [str(uuid.uuid4())]}
    ).encode()
    status, _, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    usage = (answer or {}).get("usage") or {}
    smoke.record(
        "no-evidence refusal",
        status == 200
        and bool(answer)
        and answer.get("refused") is True
        and answer.get("refusal_reason") == "low_evidence"
        and answer.get("citations") == []
        and usage.get("calls") == 0,
        f"status={status} answer={answer}",
    )

    status, header, problem = smoke.get_json(
        "POST", "/v1/query", b'{"question": ""}', {"Content-Type": "application/json"}
    )
    smoke.record(
        "empty question 422 problem+json",
        status == 422
        and bool(problem)
        and (_header(header, "Content-Type") or "").startswith("application/problem+json")
        and "request_id" in problem,
        f"status={status} headers={header} problem={problem}",
    )

    body, ctype = multipart("notes.txt", b"definitely not a pdf")
    status, _, problem = smoke.get_json("POST", "/v1/documents", body, {"Content-Type": ctype})
    smoke.record("non-PDF 422", status == 422, f"status={status} problem={problem}")

    status, _, _ = smoke.request("DELETE", f"/v1/documents/{same_id}")
    smoke.record("delete 204", status == 204, f"status={status}")

    qbody = json.dumps({"question": "What does self-attention do?"}).encode()
    status, _, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    smoke.record(
        "query after delete refused",
        status == 200 and bool(answer) and answer.get("refused") is True,
        f"status={status} answer={answer}",
    )

    status, _, _ = smoke.request("DELETE", f"/v1/documents/{same_id}")
    smoke.record("delete again 404", status == 404, f"status={status}")


def sample_question() -> str:
    path = Path(__file__).resolve().parent.parent / "evaluation" / "demo_questions.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("questions", []):
            if item.get("question"):
                return str(item["question"])
    return "What is the core purpose of the AI Risk Management Framework?"


def run_live(smoke: Smoke) -> None:
    smoke.poll("/healthz", "/healthz", lambda s, h, b: s == 200, "service never became healthy")
    smoke.poll("/readyz 200", "/readyz", lambda s, h, b: s == 200, "service never became ready")

    status, _, listing = smoke.get_json("GET", "/v1/documents")
    docs = (listing or {}).get("items", [])
    smoke.record(
        "documents exist", status == 200 and len(docs) >= 1, f"status={status} n={len(docs)}"
    )

    qbody = json.dumps({"question": sample_question()}).encode()
    status, _, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    smoke.record(
        "query explained",
        status == 200
        and bool(answer)
        and answer.get("refused") is False
        and len(answer.get("citations", [])) >= 1,
        f"status={status} refused={(answer or {}).get('refused')} "
        f"citations={len((answer or {}).get('citations', []))}",
    )


def run_ephemeral(smoke: Smoke, args: argparse.Namespace) -> None:
    """Nine checks against the release image (A1.4). Costs at most one provider request."""
    commit = args.expect_commit
    smoke.record(
        "image revision label equals the commit",
        bool(args.expect_image_revision) and args.expect_image_revision == commit,
        f"label={args.expect_image_revision!r} commit={commit!r}",
    )

    smoke.poll(
        "healthz 200 and commit matches",
        "/healthz",
        lambda s, h, b: s == 200 and json.loads(b).get("commit") == commit,
        f"commit != {commit}",
    )

    def ready(s: int, h: dict, b: bytes) -> bool:
        if s != 200:
            return False
        doc = json.loads(b)
        checks = doc.get("checks", {})
        return (
            doc.get("status") == "ready"
            and checks.get("database") == "ok"
            and checks.get("embedder") == "ok"
        )

    started = time.monotonic()
    smoke.poll("readyz database and embedder ok", "/readyz", ready, "not ready")
    smoke.info["readyz_first_latency_s"] = round(time.monotonic() - started, 3)

    status, header, _ = smoke.request("GET", "/")
    csp = _header(header, "Content-Security-Policy") or ""
    ctype = _header(header, "Content-Type") or ""
    smoke.record(
        "landing page 200 HTML with CSP",
        status == 200
        and ctype.startswith("text/html")
        and "default-src 'none'" in csp
        and "frame-ancestors 'none'" in csp
        and (_header(header, "X-Content-Type-Options") or "").lower() == "nosniff"
        and (_header(header, "Referrer-Policy") or "").lower() == "no-referrer",
        f"status={status} content_type={ctype!r} csp={csp!r}",
    )

    status, _, listing = smoke.get_json("GET", "/v1/documents")
    items = (listing or {}).get("items", [])
    smoke.info["document_count"] = len(items)
    smoke.record(
        "demo documents listed",
        status == 200 and len(items) >= DEMO_DOCUMENT_COUNT,
        f"status={status} count={len(items)}",
    )

    qbody = json.dumps({"question": sample_question()}).encode()
    started = time.monotonic()
    status, _, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    smoke.info["first_query_latency_s"] = round(time.monotonic() - started, 3)
    smoke.record(
        "sample question answered with a citation",
        status == 200
        and bool(answer)
        and answer.get("refused") is False
        and len(answer.get("citations", [])) >= 1,
        f"status={status} refused={(answer or {}).get('refused')} "
        f"citations={len((answer or {}).get('citations', []))} "
        f"usage={(answer or {}).get('usage')}",
    )

    qbody = json.dumps({"question": NO_EVIDENCE_QUESTION}).encode()
    started = time.monotonic()
    status, _, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    smoke.info["warm_query_latency_s"] = round(time.monotonic() - started, 3)
    smoke.info["warm_query_note"] = "refused query, no provider call (one-request budget)"
    usage = (answer or {}).get("usage") or {}
    smoke.record(
        "nonsense question refused",
        status == 200
        and bool(answer)
        and answer.get("refused") is True
        and answer.get("refusal_reason") == "low_evidence"
        and answer.get("citations") == []
        and usage.get("calls") == 0,
        f"status={status} refused={(answer or {}).get('refused')} "
        f"reason={(answer or {}).get('refusal_reason')} calls={usage.get('calls')}",
    )

    pdf = make_pdf([PDF_TEXT])
    body, ctype = multipart("smoke.pdf", pdf)
    status, _, problem = smoke.get_json("POST", "/v1/documents", body, {"Content-Type": ctype})
    smoke.record("anonymous upload 403", status == 403, f"status={status} problem={problem}")

    # Checks 6 and 7 used two slots of the same per-IP window. Wait out the 60 s
    # window, then send cap+1 refused queries; the (cap+1)th must be 429.
    cap = max(1, args.ip_per_min)
    time.sleep(61)
    statuses = []
    retry_after = None
    for index in range(cap + 1):
        qbody = json.dumps({"question": NO_EVIDENCE_QUESTION}).encode()
        status, header, _ = smoke.get_json(
            "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
        )
        statuses.append(status)
        if index == cap:
            retry_after = _header(header, "Retry-After")
    smoke.info["limits_check"] = {
        "approach": (
            "waited 61 s after checks 6-7 to clear the 60 s per-IP window; "
            "sent cap+1 refused queries"
        ),
        "cap": cap,
        "statuses": statuses,
    }
    smoke.record(
        "rapid queries hit the per-IP cap",
        all(status == 200 for status in statuses[:cap])
        and statuses[cap] == 429
        and retry_after is not None
        and int(retry_after) >= 1,
        f"cap={cap} statuses={statuses} retry_after={retry_after!r}",
    )

    smoke.info["provider_requests"] = 1
    smoke.info["runner_type"] = args.runner_type
    smoke.info["container_limit"] = args.container_limit
    smoke.info["conditions"] = args.conditions
    smoke.info["mem_peak_mib"] = mem_peak_mib(args.mem_file)


def write_json(smoke: Smoke, args: argparse.Namespace) -> None:
    if not args.json_out:
        return
    payload = {
        "mode": args.mode,
        "base": args.base,
        "expect_commit": args.expect_commit,
        "expect_image_revision": args.expect_image_revision,
        "ok": smoke.ok,
        "checks": smoke.results,
        "info": smoke.info,
    }
    Path(args.json_out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "ephemeral":
        if not args.expect_commit:
            parser.error("--mode ephemeral requires --expect-commit")
        if not args.expect_image_revision:
            parser.error("--mode ephemeral requires --expect-image-revision")
        if not args.check_limits:
            parser.error("--mode ephemeral requires --check-limits")
    timeout = args.timeout or (180 if args.mode == "ci" else 900)
    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    smoke = Smoke(args.base, timeout, api_key or None)

    try:
        if args.mode == "ci":
            run_ci(smoke)
        elif args.mode == "ephemeral":
            run_ephemeral(smoke, args)
        else:
            run_live(smoke)
            if args.expect_commit:
                smoke.poll(
                    "healthz commit",
                    "/healthz",
                    lambda s, h, b: s == 200 and json.loads(b).get("commit") == args.expect_commit,
                    f"commit != {args.expect_commit}",
                )
    except Exception as exc:
        smoke.record("smoke script completed", False, f"{type(exc).__name__}: {exc}")
    finally:
        write_json(smoke, args)

    print(f"smoke_http {args.mode}: {smoke.checks} checks, ok={smoke.ok}")
    return 0 if smoke.ok else 1


if __name__ == "__main__":
    sys.exit(main())
