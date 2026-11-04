"""Unit tests for scripts/smoke_http.py: the multipart helper and the parser."""

from __future__ import annotations

import pytest

from scripts.smoke_http import build_parser, main, mem_peak_mib, multipart


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


class TestEphemeralParser:
    def test_requires_commit_revision_and_limits(self) -> None:
        with pytest.raises(SystemExit):
            main(["--base", "http://x", "--mode", "ephemeral"])

    def test_accepts_ephemeral_args(self) -> None:
        args = build_parser().parse_args(
            [
                "--base",
                "http://127.0.0.1:8000",
                "--mode",
                "ephemeral",
                "--expect-commit",
                "abc123",
                "--expect-image-revision",
                "abc123",
                "--check-limits",
                "--ip-per-min",
                "5",
                "--json-out",
                "smoke.json",
                "--mem-file",
                "mem.txt",
            ]
        )
        assert args.mode == "ephemeral"
        assert args.expect_image_revision == "abc123"
        assert args.check_limits is True
        assert args.ip_per_min == 5
        assert args.json_out == "smoke.json"


def test_mem_peak_mib(tmp_path) -> None:
    path = tmp_path / "mem.txt"
    path.write_text("100.5MiB / 512MiB\n200MiB / 512MiB\n1.5GiB / 2GiB\n", encoding="utf-8")
    assert mem_peak_mib(str(path)) == 1536.0
