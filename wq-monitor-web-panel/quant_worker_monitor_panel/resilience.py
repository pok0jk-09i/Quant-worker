"""Resilience Patterns — Circuit Breaker, Rate Limiter, Bulkhead.

Design principles (from pyresilience / resilience4j):
  - Circuit Breaker: CLOSED → OPEN (failures exceed threshold) → HALF_OPEN (probe) → CLOSED
  - Rate Limiter: token bucket algorithm — N tokens per second, burst=N
  - Bulkhead: separate pools for reads (GET) vs writes (POST /simulations)

All patterns are decorator-based for easy integration with existing code.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════

class CircuitState(Enum):
    CLOSED = auto()      # normal operation
    OPEN = auto()        # failing — reject immediately
    HALF_OPEN = auto()   # probe — allow one request through


@dataclass
class CircuitBreaker:
    """Stateful circuit breaker for HTTP calls.

    Transitions:
      CLOSED ──[failure_threshold reached]──▶ OPEN
      OPEN   ──[timeout_seconds elapsed]───▶ HALF_OPEN
      HALF_OPEN ──[success]────────────────▶ CLOSED
      HALF_OPEN ──[failure]────────────────▶ OPEN
    """

    name: str = "default"
    failure_threshold: int = 5
    timeout_seconds: float = 60.0
    half_open_max_requests: int = 3

    def __post_init__(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_requests: int = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def _transition(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_requests = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
        print(f"[circuit:{self.name}] {old.name} → {new_state.name}", flush=True)

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_requests += 1
                if self._half_open_requests >= self.half_open_max_requests:
                    self._transition(CircuitState.CLOSED)

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
                self._transition(CircuitState.OPEN)

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                return self._half_open_requests < self.half_open_max_requests
            # OPEN: check if timeout has elapsed
            if time.time() - self._last_failure_time >= self.timeout_seconds:
                self._transition(CircuitState.HALF_OPEN)
                return True
            return False


# ═══════════════════════════════════════════════════════════════════════════
# Rate Limiter (Token Bucket)
# ═══════════════════════════════════════════════════════════════════════════

class TokenBucket:
    """Token bucket rate limiter.

    tokens_per_second: steady-state rate
    burst: max tokens that can accumulate
    """

    def __init__(self, tokens_per_second: float, burst: int | None = None) -> None:
        self.rate = tokens_per_second
        self.burst = burst or max(1, int(tokens_per_second * 2))
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens. Returns True if successful."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_and_acquire(self, tokens: float = 1.0, timeout: float = 30.0) -> bool:
        """Wait until tokens are available or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire(tokens):
                return True
            time.sleep(0.5)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Resilient function decorator
# ═══════════════════════════════════════════════════════════════════════════

def with_circuit_breaker(
    breaker: CircuitBreaker,
    fallback_value: Any = None,
) -> Callable:
    """Decorator: wrap a function with circuit breaker protection."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not breaker.allow_request():
                print(f"[circuit:{breaker.name}] OPEN — rejecting call to {func.__name__}", flush=True)
                return fallback_value

            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception:
                breaker.record_failure()
                raise

        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════════════════════
# Pre-built breakers for Quant worker API calls
# ═══════════════════════════════════════════════════════════════════════════

# Simulation breaker: opens after 5 consecutive failures, resets after 10 min
simulation_breaker = CircuitBreaker(name="simulations", failure_threshold=5, timeout_seconds=600)

# Alpha fetch breaker: opens after 8 failures, resets after 5 min
alpha_fetch_breaker = CircuitBreaker(name="alpha_fetch", failure_threshold=8, timeout_seconds=300)

# Auth breaker: opens after 3 failures, resets after 2 min
auth_breaker = CircuitBreaker(name="authentication", failure_threshold=3, timeout_seconds=120)

# Simulation rate limiter: max 1 submission per second, burst of 3
simulation_limiter = TokenBucket(tokens_per_second=1.0, burst=3)
