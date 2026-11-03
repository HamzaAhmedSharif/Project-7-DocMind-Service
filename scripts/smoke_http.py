"""HTTP smoke test for DocMind (M4.3): standard library only.

Prints `PASS <name>` or `FAIL <name>: <reason>` for every check and exits 1
if any check failed (used by the CI image job and the local measurements).
"""

from __future__ import annotations

import argparse
import json
import os
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocMind HTTP smoke test.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--mode", choices=["ci", "live"], required=True)
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--expect-commit", default=None)
    parser.add_argument("--api-key-env", default=None)
    return parser


class Smoke:
    def __init__(self, base: str, deadline_s: int, api_key: str | None) -> None:
        self.base = base.rstrip("/")
        self.deadline_s = deadline_s
        self.api_key = api_key
        self.ok = True
        self.checks = 0

    def record(self, name: str, passed: bool, reason: str = "") -> None:
        self.checks += 1
        if not passed:
            self.ok = False
            print(f"FAIL {name}: {reason}")
        else:
            print(f"PASS {name}")

    def request(self, method: str, path: str, body=None, headers=None):
        headers = dict(headers or {})
        if self.api_key:
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

    def get_json(self, method: str, path: str, body=None, headers=None):
        status, header, raw = self.request(method, path, body, headers)
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

    pdf = make_pdf([PDF_TEXT])
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

    # M6 adds a relevance floor; until then nonsense text still retrieves the one
    # chunk, so the no-evidence path is exercised with a document filter that matches nothing.
    qbody = json.dumps({"question": "zzzz qqqq", "document_ids": [str(uuid.uuid4())]}).encode()
    status, _, answer = smoke.get_json(
        "POST", "/v1/query", qbody, {"Content-Type": "application/json"}
    )
    usage = (answer or {}).get("usage") or {}
    smoke.record(
        "no-evidence refusal",
        status == 200
        and bool(answer)
        and answer.get("refused") is True
        and answer.get("refusal_reason") == "no_evidence"
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
    path = Path(__file__).resolve().parent.parent / "evaluation" / "demo_corpus.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data if isinstance(data, list) else data.get("items", []):
            if item.get("question"):
                return str(item["question"])
    return "self-attention"


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
        f"status={status} answer={answer}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    timeout = args.timeout or (180 if args.mode == "ci" else 900)
    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    smoke = Smoke(args.base, timeout, api_key or None)

    if args.mode == "ci":
        run_ci(smoke)
    else:
        run_live(smoke)
        if args.expect_commit:
            smoke.poll(
                "healthz commit",
                "/healthz",
                lambda s, h, b: s == 200 and json.loads(b).get("commit") == args.expect_commit,
                f"commit != {args.expect_commit}",
            )

    print(f"smoke_http {args.mode}: {smoke.checks} checks, ok={smoke.ok}")
    return 0 if smoke.ok else 1


if __name__ == "__main__":
    sys.exit(main())
