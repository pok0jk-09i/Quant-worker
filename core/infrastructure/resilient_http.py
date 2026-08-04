"""Resilient HTTP client for the BRAIN API.

REPLACES the ad-hoc ``_request_with_retry`` with a principled design:

* Retry ONLY transient failures: network errors, timeouts, HTTP 429, and
  5xx. Permanent client errors (4xx except 401/429) are returned
  *immediately with their body preserved* so callers can diagnose — e.g.
  the previous code discarded a 403 body, hiding why an alpha was
  rejected by BRAIN (region-specific hard checks).
* Exponential backoff with FULL JITTER (AWS-style) to avoid a thundering
  herd when many worker threads retry simultaneously.
* A per-service :class:`CircuitBreaker` so sustained 5xx stops being
  hammered and fails fast with a clear signal.
* A typed :class:`HttpResult` so the ambiguous ``None`` return (which
  callers forgot to check) is eliminated — every outcome is explicit.

This module has no third-party dependencies beyond ``requests`` (already
required by the stack).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen

API_BASE = "https://api.worldquantbrain.com"
HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json",
}

# Status codes we treat as transient and retry. Everything else (2xx, and
# 4xx except 401/429) is terminal and returned as-is.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass
class HttpResult:
    """Explicit outcome of an HTTP operation. Never ``None``."""

    ok: bool
    status_code: Optional[int]
    body: Any = None            # parsed JSON when available, else None
    raw_text: str = ""          # raw response text (always captured)
    headers: dict = field(default_factory=dict)  # response headers (e.g. Location)
    error: Optional[str] = None
    attempt: int = 0

    def __bool__(self) -> bool:  # convenience: ``if result:``
        return self.ok

    @property
    def is_server_error(self) -> bool:
        return self.status_code is not None and 500 <= self.status_code < 600


class ResilientSession:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = API_BASE,
        max_attempts: int = 6,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
        timeout: tuple[float, float] = (10, 60),
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(username, password)
        self._session.headers.update(HEADERS)
        self.base_url = base_url
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.timeout = timeout
        self._breaker = breaker or CircuitBreaker("brain-api")

    # -- public API -------------------------------------------------------
    def authenticate(self) -> HttpResult:
        # _is_auth=True marks this call so the 401 handler in _do() will NOT
        # try to re-authenticate (which would recurse). It is forwarded all
        # the way down to _do().
        return self.request("POST", "/authentication", json=None, _is_auth=True)

    def get(self, path: str) -> HttpResult:
        return self.request("GET", path)

    def post(self, path: str, *, json: Any | None = None) -> HttpResult:
        return self.request("POST", path, json=json)

    def request(
        self, method: str, path: str, *, json: Any | None = None, _is_auth: bool = False
    ) -> HttpResult:
        try:
            return self._breaker.call(
                lambda: self._do(method, path, json=json, _is_auth=_is_auth)
            )
        except CircuitBreakerOpen as exc:
            return HttpResult(
                ok=False,
                status_code=None,
                error=f"circuit_open:{exc.retry_after:.0f}s",
            )

    # -- internals --------------------------------------------------------
    def _backoff(self, attempt: int) -> float:
        """Exponential cap + FULL jitter (uniform in [0, cap])."""
        cap = min(self.max_backoff, self.base_backoff * (2 ** (attempt - 1)))
        return random.uniform(0.0, cap)

    def _do(
        self,
        method: str,
        path: str,
        *,
        json: Any | None,
        _is_auth: bool = False,
    ) -> HttpResult:
        url = self.base_url + path
        last: HttpResult | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                if method == "GET":
                    resp = self._session.get(url, timeout=self.timeout)
                else:
                    resp = self._session.post(url, json=json, timeout=self.timeout)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last = HttpResult(
                    ok=False, status_code=None,
                    error=f"network:{exc}", attempt=attempt,
                )
                if attempt < self.max_attempts:
                    time.sleep(self._backoff(attempt))
                    continue
                return last

            body = self._safe_json(resp)
            last = HttpResult(
                ok=200 <= resp.status_code < 300,
                status_code=resp.status_code,
                body=body,
                raw_text=resp.text,
                headers=dict(resp.headers),
                attempt=attempt,
            )

            # 401 -> re-authenticate then retry (once per loop iteration).
            if resp.status_code == 401 and not _is_auth:
                self.authenticate()
                if attempt < self.max_attempts:
                    continue
                return last

            # Transient server/rate-limit errors -> backoff and retry.
            if resp.status_code in _RETRYABLE_STATUS:
                if attempt < self.max_attempts:
                    time.sleep(self._backoff(attempt))
                    continue
                return last

            # Terminal: 2xx, or 4xx (except 401/429). Body is PRESERVED so
            # callers can read rejection reasons (e.g. a 403 explanation).
            return last

        return last or HttpResult(ok=False, status_code=None, error="unknown",
                                  attempt=self.max_attempts)

    @staticmethod
    def _safe_json(resp: requests.Response) -> Any | None:
        try:
            return resp.json()
        except Exception:
            return None
