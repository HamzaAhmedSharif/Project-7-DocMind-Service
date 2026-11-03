"""Unit tests for scripts/smoke_http.py: the multipart helper and the parser."""

from __future__ import annotations

import pytest

from scripts.smoke_http import build_parser, multipart


class TestMultipart:
    def test_returns_body_and_content_type(self) -> None:
        body, ctype = multipart("t.pdf", b"PDFDATA")
        assert ctype.startswith("multipart/form-data; boundary=----docmind")
        boundary = ctype.split("boundary=", 1)[1]
        assert body.startswith(f"--{boundary}\r\n".encode())
        assert b'name="file"; filename="t.pdf"' in body
        assert b"Content-Type: application/pdf" in body
        assert body.endswith(f"--{boundary}--\r\n".encode())
        assert b"PDFDATA" in body

    def test_custom_field(self) -> None:
        body, _ = multipart("t.pdf", b"x", field="doc")
        assert b'name="doc"; filename="t.pdf"' in body


class TestParser:
    def test_ci_defaults(self) -> None:
        args = build_parser().parse_args(["--base", "http://127.0.0.1:8000", "--mode", "ci"])
        assert args.base == "http://127.0.0.1:8000"
        assert args.mode == "ci"
        assert args.expect_commit is None
        assert args.api_key_env is None

    def test_live_accepts_live_args(self) -> None:
        args = build_parser().parse_args(
            [
                "--base",
                "https://example.com",
                "--mode",
                "live",
                "--expect-commit",
                "abc123",
                "--api-key-env",
                "DOCMIND_API_KEY",
                "--timeout",
                "999",
            ]
        )
        assert args.mode == "live"
        assert args.expect_commit == "abc123"
        assert args.api_key_env == "DOCMIND_API_KEY"
        assert args.timeout == 999

    @pytest.mark.parametrize("missing", [["--mode", "ci"], ["--base", "http://x"]])
    def test_requires_both(self, missing: list[str]) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(missing)
