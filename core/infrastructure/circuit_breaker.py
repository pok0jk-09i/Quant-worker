"""Circuit breaker for outbound API calls.

WHY THIS EXISTS
---------------
We observed long stretches where BRAIN returned HTTP 500. Hammering a
failing endpoint is pointless and risks rate-limit bans. A circuit
breaker *trips OPEN* after N failures within a sliding window, refuses
calls for a cool-down period, then allows a single probe (HALF_OPEN).
Only after the probe succeeds does it CLOSE again.

This is the standard resilience pattern (Nygard, "Release It!"; see also
the ``tenacity`` / ``pybreaker`` libraries) implemented with **zero
dependencies** so it runs in the locked-down research interpreter.

Thread-safety: a single ``Lock`` guards all state transitions so multiple
worker threads sharing one breaker (per-service) are safe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class BreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5          # failures in window -> OPEN
    success_threshold: int = 2          # consecutive successes to CLOSE from HALF_OPEN
    window_seconds: float = 60.0        # sliding window for counting failures
    cooldown_seconds: float = 30.0      # how long to stay OPEN before probing


class CircuitBreakerOpen(Exception):
    """Raised when a call is attempted while the breaker is OPEN."""

    def __init__(self, service: str, retry_after: float) -> None:
        super().__init__(
            f"Circuit breaker OPEN for {service}; retry after {retry_after:.0f}s"
        )
        self.service = service
        self.retry_after = retry_after


class CircuitBreaker:
    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        self.name = name
        self.cfg = config or CircuitBreakerConfig()
        self._state = BreakerState.CLOSED
        self._failures: list[float] = []
        self._successes = 0
        self._opened_at = 0.0
        self._lock = Lock()

    # -- introspection ----------------------------------------------------
    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._maybe_half_open()
            return {
                "name": self.name,
                "state": self._state.value,
                "recent_failures": len(self._failures),
            }

    # -- transitions ------------------------------------------------------
    def _maybe_half_open(self) -> None:
        if self._state == BreakerState.OPEN and (
            time.monotonic() - self._opened_at >= self.cfg.cooldown_seconds
        ):
            self._state = BreakerState.HALF_OPEN
            self._successes = 0

    def _record_failure(self) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t <= self.cfg.window_seconds]
        self._failures.append(now)
        if self._state == BreakerState.HALF_OPEN:
            # probe failed -> re-open
            self._state = BreakerState.OPEN
            self._opened_at = now
            return
        if len(self._failures) >= self.cfg.failure_threshold:
            self._state = BreakerState.OPEN
            self._opened_at = now

    def _record_success(self) -> None:
        if self._state == BreakerState.HALF_OPEN:
            self._successes += 1
            if self._successes >= self.cfg.success_threshold:
                self._state = BreakerState.CLOSED
                self._failures.clear()
        else:
            self._failures.clear()

    # -- execution --------------------------------------------------------
    def call(self, func: Callable[[], T], *, on_open: Callable[[], T] | None = None) -> T:
        """Run ``func`` under breaker protection.

        Raises ``CircuitBreakerOpen`` (or returns ``on_open()``) when OPEN.
        Any exception from ``func`` is recorded as a failure and re-raised.
        """
        with self._lock:
            self._maybe_half_open()
            if self._state == BreakerState.OPEN:
                if on_open is not None:
                    return on_open()
                remaining = self.cfg.cooldown_seconds - (time.monotonic() - self._opened_at)
                raise CircuitBreakerOpen(self.name, max(0.0, remaining))
        try:
            result = func()
        except Exception:
            with self._lock:
                self._record_failure()
            raise
        with self._lock:
            self._record_success()
        return result
