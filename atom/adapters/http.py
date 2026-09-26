"""Proxy-aware HTTP client shared by every adapter.

One place for the three things that must be uniform across five brokers:

* **Egress binding.** Every request goes through the account's forward proxy, so
  the source address is structural rather than per-call. A request either goes
  through the proxy or fails to connect — there is no "works but from the wrong
  IP" state, which matters because on Dhan that state has no error code (D-173).
* **Rate limiting.** A token bucket per (account, category), capped well below
  every broker's ceiling.
* **Retry.** Exponential backoff *with jitter*. A fixed interval synchronises
  retries across threads and makes bursts worse — Shoonya's own documentation
  says so.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from atom.domain.errors import BrokerError, RateLimitError, TransientError

Method = Literal["GET", "POST", "PUT", "DELETE"]

DEFAULT_TIMEOUT = 15.0
MAX_ATTEMPTS = 4
BASE_BACKOFF = 0.5
MAX_BACKOFF = 8.0


@dataclass(slots=True)
class TokenBucket:
    """A simple per-second rate limiter.

    Capped deliberately low: ATOM places a handful of orders a day against
    ceilings of 7,000-10,000, so the limiter exists as a compliance control
    (D-088, staying far under the 10 OPS registration threshold) rather than for
    throughput.
    """

    rate_per_second: float
    capacity: float
    _tokens: float = field(default=0.0, init=False)
    _last: float = field(default_factory=time.monotonic, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity

    def take(self, tokens: float = 1.0) -> None:
        """Block until ``tokens`` are available."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._last) * self.rate_per_second
                )
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self.rate_per_second
            time.sleep(min(wait, 1.0))


def backoff_delay(attempt: int, *, rng: random.Random | None = None) -> float:
    """Exponential backoff with full jitter, for ``attempt`` starting at 1.

    Full jitter (uniform over ``[0, base * 2**n]``) rather than a fixed multiple:
    it is what stops several retrying callers from re-colliding.
    """
    r = rng or random
    ceiling = min(MAX_BACKOFF, BASE_BACKOFF * (2 ** (attempt - 1)))
    return r.uniform(0.0, ceiling)


class BrokerHttpClient:
    """An HTTP client bound to one account's egress proxy.

    Adapters own the *meaning* of a response; this class owns getting it, safely.
    It deliberately does **not** interpret bodies — error classification is each
    adapter's job, because the five brokers signal failure in five ways (Shoonya
    returns HTTP 200 on rejection, so a status-code-only reading would record a
    rejected order as placed).
    """

    def __init__(
        self,
        *,
        base_url: str,
        proxy_url: str | None,
        broker_code: str,
        orders_per_second: int = 2,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.broker_code = broker_code
        self._order_bucket = TokenBucket(rate_per_second=float(orders_per_second), capacity=2.0)
        self._read_bucket = TokenBucket(rate_per_second=5.0, capacity=5.0)
        self._client = httpx.Client(
            base_url=base_url,
            proxy=proxy_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            verify=True,  # never disabled, not even against a sandbox
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BrokerHttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(
        self,
        method: Method,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        content: bytes | str | None = None,
        is_order: bool = False,
        retry: bool = True,
    ) -> httpx.Response:
        """Send one request, retrying only transport-level and 429/5xx failures.

        ``is_order`` routes through the order rate bucket. A 4xx other than 429 is
        returned as-is for the adapter to classify — retrying a rejection would
        discard the information it carries.
        """
        bucket = self._order_bucket if is_order else self._read_bucket
        last_exc: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            bucket.take()
            try:
                response = self._client.request(
                    method,
                    path,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                    content=content,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if not retry or attempt == MAX_ATTEMPTS:
                    raise TransientError(
                        f"{method} {path} failed after {attempt} attempt(s): {exc}",
                        broker=self.broker_code,
                    ) from exc
                time.sleep(backoff_delay(attempt))
                continue

            if response.status_code == 429:
                if not retry or attempt == MAX_ATTEMPTS:
                    raise RateLimitError(
                        f"{method} {path} rate limited after {attempt} attempt(s)",
                        broker=self.broker_code,
                        raw=response.text,
                    )
                time.sleep(self._retry_after(response, attempt))
                continue

            if 500 <= response.status_code < 600:
                if not retry or attempt == MAX_ATTEMPTS:
                    raise TransientError(
                        f"{method} {path} returned {response.status_code}",
                        broker=self.broker_code,
                        raw=response.text,
                    )
                time.sleep(backoff_delay(attempt))
                continue

            return response

        raise TransientError(  # pragma: no cover - loop always returns or raises
            f"{method} {path} exhausted retries", broker=self.broker_code, raw=last_exc
        )

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        """Honour ``Retry-After`` when present, otherwise back off with jitter."""
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(MAX_BACKOFF, float(header))
            except ValueError:
                pass
        return backoff_delay(attempt)


def require_2xx(response: httpx.Response, *, broker: str, context: str) -> httpx.Response:
    """Assert a successful status, or raise a generic broker error.

    Adapters call this only for endpoints where HTTP status is a reliable signal.
    On Shoonya it is not — a rejection arrives as HTTP 200 with ``stat: Not_Ok``
    — so that adapter checks ``stat`` first and never calls this on order paths.
    """
    if response.is_success:
        return response
    raise BrokerError(f"{context}: HTTP {response.status_code}", broker=broker, raw=response.text)
