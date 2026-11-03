import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from openai import OpenAI

from docmind_service.config import get_settings
from docmind_service.db import load_dotenv, load_local_env

HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "retry-after",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file)
    else:
        load_local_env()
    settings = get_settings()
    if not settings.llm_api_key_value:
        print("PENDING-H6")
        return 0
    client = OpenAI(
        api_key=settings.llm_api_key_value,
        base_url=settings.llm_base_url,
        max_retries=0,
    )
    started = time.perf_counter()
    try:
        raw = client.chat.completions.with_raw_response.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            reasoning_effort=settings.llm_reasoning_effort,
            max_completion_tokens=settings.llm_max_completion_tokens,
            timeout=60,
        )
        response = raw.parse()
        elapsed = time.perf_counter() - started
        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        print(f"model: {settings.llm_model}")
        print(f"answer: {'ok' if text.lower() == 'ok' else 'not ok'}")
        print(f"prompt_tokens: {int(getattr(usage, 'prompt_tokens', 0) or 0)}")
        print(f"completion_tokens: {int(getattr(usage, 'completion_tokens', 0) or 0)}")
        print(f"api_seconds: {elapsed:.3f}")
        headers = {key: raw.headers.get(key) for key in HEADERS if raw.headers.get(key) is not None}
        for key, value in headers.items():
            print(f"{key}: {value}")
        out = Path(__file__).resolve().parent.parent / "evaluation" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "provider-limits.json").write_text(
            json.dumps(
                {
                    "date": date.today().isoformat(),
                    "model": settings.llm_model,
                    "ok": text.lower() == "ok",
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    "api_seconds": round(elapsed, 3),
                    "headers": headers,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        print(f"provider call failed: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
