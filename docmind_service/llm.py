import logging
import math
import re
import time
from collections.abc import Callable
from threading import Lock

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from docmind_service.config import Settings
from docmind_service.domain import LLMResult, ProviderError
from docmind_service.metrics import LLM_SHED

logger = logging.getLogger("docmind.llm")
STATS = {"calls": 0, "retries": 0, "throttled_seconds": 0.0}
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TRY_AGAIN = re.compile(r"try again in\s+(.+?)(?:\.(?:\s|$)|$)", re.IGNORECASE | re.DOTALL)
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)", re.IGNORECASE)
_DAILY = re.compile(r"\b(?:requests?|tokens?)\s+per\s+day\b|\bper\s+day\b|\bdaily\b", re.I)


def _duration_seconds(text: str) -> int | None:
    match = _TRY_AGAIN.search(text)
    if not match:
        return None
    total = 0.0
    found = False
    for value, unit in _DURATION.findall(match.group(1)):
        scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit.lower()]
        total += float(value) * scale
        found = True
    return math.ceil(total) if found else None


def _retry_after(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is not None:
        try:
            return max(0, math.ceil(float(value)))
        except (TypeError, ValueError):
            pass
    return _duration_seconds(str(exc))


class TokenBucket:
    """Continuous refill; take(n) reserves n units, returns seconds to wait (0 if available)."""

    def __init__(self, per_minute, *, burst=None, clock: Callable[[], float] = time.monotonic):
        self.rate = float(per_minute) / 60.0
        self.capacity = float(burst if burst is not None else per_minute)
        self.level = self.capacity
        self.clock = clock
        self.last = clock()
        self._lock = Lock()

    def take(self, amount: float) -> float:
        with self._lock:
            now = self.clock()
            self.level = min(self.capacity, self.level + (now - self.last) * self.rate)
            self.last = now
            self.level -= amount
            return 0.0 if self.level >= 0 else -self.level / self.rate

    def give_back(self, amount: float) -> None:
        with self._lock:
            self.level = min(self.capacity, self.level + amount)


class HostedLLM:
    """OpenAI-compatible chat client with bounded retries and shared RPM/TPM pacing."""

    def __init__(
        self,
        settings: Settings,
        *,
        client=None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._pacing = Lock()
        rpm = settings.hosted_rpm * 0.9
        tpm = settings.hosted_tpm * 0.9
        self.requests = TokenBucket(rpm, clock=clock)
        self.tokens = TokenBucket(tpm, clock=clock)

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client
        key = self.settings.llm_api_key_value
        if not key:
            raise ProviderError("LLM_API_KEY is not configured")
        self._client = OpenAI(
            api_key=key,
            base_url=self.settings.llm_base_url,
            max_retries=0,
        )
        return self._client

    def _acquire(self, estimate: int) -> float:
        if estimate > self.tokens.capacity:
            LLM_SHED.inc()
            raise ProviderError("request exceeds the per-minute limit")
        with self._pacing:
            wait = max(self.requests.take(1), self.tokens.take(estimate))
            if wait > self.settings.llm_max_wait_seconds:
                self.requests.give_back(1)
                self.tokens.give_back(estimate)
                LLM_SHED.inc()
                raise ProviderError("request would wait too long", retry_after=math.ceil(wait))
            if wait > 0:
                self._sleep(wait)
                STATS["throttled_seconds"] += wait
            return wait

    def complete(self, prompt: str) -> LLMResult:
        settings = self.settings
        estimate = len(prompt) // 3 + 600
        wait_seconds = self._acquire(estimate)
        attempts = 0
        retries = 0
        api_seconds = 0.0
        last_retry_after: int | None = None
        while True:
            attempts += 1
            STATS["calls"] += 1
            call_started = time.perf_counter()
            try:
                response = self._get_client().chat.completions.create(
                    model=settings.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    reasoning_effort=settings.llm_reasoning_effort,
                    max_completion_tokens=settings.llm_max_completion_tokens,
                    timeout=60,
                )
                api_seconds += time.perf_counter() - call_started
                usage = getattr(response, "usage", None)
                text = _THINK_RE.sub("", response.choices[0].message.content or "").strip()
                if not text:
                    raise ProviderError("provider returned an empty answer", retry_after=5)
                actual = int(getattr(usage, "prompt_tokens", 0) or 0) + int(
                    getattr(usage, "completion_tokens", 0) or 0
                )
                if actual > estimate:
                    self.tokens.take(actual - estimate)
                else:
                    self.tokens.give_back(estimate - actual)
                return LLMResult(
                    text=text,
                    calls=attempts,
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                    api_seconds=api_seconds,
                    wait_seconds=wait_seconds,
                )
            except RateLimitError as exc:
                api_seconds += time.perf_counter() - call_started
                message = str(exc)
                last_retry_after = _retry_after(exc)
                if _DAILY.search(message):
                    raise ProviderError(
                        "provider daily limit reached", retry_after=last_retry_after or 3600
                    ) from exc
                if attempts >= 3:
                    raise ProviderError("provider rate limited the request") from exc
                delay = last_retry_after if last_retry_after is not None else 1
                self._sleep(min(float(delay), 20) + 0.5)
                retries += 1
                STATS["retries"] += 1
            except APIStatusError as exc:
                api_seconds += time.perf_counter() - call_started
                status = getattr(exc, "status_code", None)
                if status == 413:
                    raise ProviderError("request too large") from exc
                if status in (401, 403):
                    logger.warning("provider authentication failed with status %s", status)
                    raise ProviderError("provider authentication failed") from exc
                raise ProviderError("provider rejected the request") from exc
            except APIConnectionError as exc:
                api_seconds += time.perf_counter() - call_started
                if retries >= 1:
                    raise ProviderError("provider unavailable", retry_after=30) from exc
                retries += 1
                STATS["retries"] += 1
                self._sleep(1.0)
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError("provider client failed") from exc
