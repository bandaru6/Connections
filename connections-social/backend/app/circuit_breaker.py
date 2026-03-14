"""Circuit breaker pattern for ML inference isolation.

Prevents cascading failures by stopping calls to a failing service
and allowing it time to recover.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is failing, requests fail fast
- HALF_OPEN: Testing if service recovered, one request allowed
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    # Number of failures before opening circuit
    failure_threshold: int = 5
    # Time window (seconds) to count failures
    failure_window: float = 60.0
    # Time (seconds) to wait before attempting recovery
    recovery_timeout: float = 30.0
    # Exceptions that should trigger the circuit breaker
    expected_exceptions: tuple = (Exception,)


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    opened_at: float | None = None
    total_rejected: int = 0


class CircuitBreaker:
    """Circuit breaker implementation for fault isolation.

    Usage:
        breaker = CircuitBreaker("insightface", config)

        @breaker
        def call_model():
            return model.predict(...)

        # Or manually:
        with breaker.protect():
            result = model.predict(...)
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failure_times: list[float] = []
        self._stats = CircuitBreakerStats()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        with self._lock:
            self._stats.state = self._state
            return self._stats

    def _count_recent_failures(self) -> int:
        """Count failures within the configured window."""
        now = time.time()
        cutoff = now - self.config.failure_window
        self._failure_times = [t for t in self._failure_times if t > cutoff]
        return len(self._failure_times)

    def _should_allow_request(self) -> bool:
        """Determine if a request should be allowed through."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if self._stats.opened_at is not None:
                    elapsed = time.time() - self._stats.opened_at
                    if elapsed >= self.config.recovery_timeout:
                        # Transition to half-open
                        self._state = CircuitState.HALF_OPEN
                        logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN")
                        return True
                return False

            # HALF_OPEN: allow one request
            return True

    def _record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._stats.successes += 1
            self._stats.last_success_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Recovery confirmed, close the circuit
                self._state = CircuitState.CLOSED
                self._failure_times.clear()
                logger.info(f"Circuit breaker '{self.name}' CLOSED after recovery")

    def _record_failure(self, exc: Exception) -> None:
        """Record a failed call."""
        with self._lock:
            now = time.time()
            self._failure_times.append(now)
            self._stats.failures += 1
            self._stats.last_failure_time = now

            if self._state == CircuitState.HALF_OPEN:
                # Recovery failed, re-open circuit
                self._state = CircuitState.OPEN
                self._stats.opened_at = now
                logger.warning(f"Circuit breaker '{self.name}' re-OPENED after failed recovery")
                return

            if self._state == CircuitState.CLOSED:
                recent_failures = self._count_recent_failures()
                if recent_failures >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._stats.opened_at = now
                    logger.warning(
                        f"Circuit breaker '{self.name}' OPENED after {recent_failures} failures "
                        f"in {self.config.failure_window}s"
                    )

    def __call__(self, func: Callable) -> Callable:
        """Decorator to wrap a function with circuit breaker."""
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if not self._should_allow_request():
                self._stats.total_rejected += 1
                raise CircuitBreakerOpen(
                    f"Circuit breaker '{self.name}' is OPEN. "
                    f"Service temporarily unavailable."
                )

            try:
                result = func(*args, **kwargs)
                self._record_success()
                return result
            except self.config.expected_exceptions as e:
                self._record_failure(e)
                raise

        return wrapper

    def protect(self):
        """Context manager for protecting a code block."""
        return CircuitBreakerContext(self)

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_times.clear()
            self._stats = CircuitBreakerStats()
            logger.info(f"Circuit breaker '{self.name}' manually reset")


class CircuitBreakerContext:
    """Context manager for circuit breaker protection."""

    def __init__(self, breaker: CircuitBreaker):
        self.breaker = breaker

    def __enter__(self):
        if not self.breaker._should_allow_request():
            self.breaker._stats.total_rejected += 1
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self.breaker.name}' is OPEN. "
                f"Service temporarily unavailable."
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.breaker._record_success()
        elif issubclass(exc_type, self.breaker.config.expected_exceptions):
            self.breaker._record_failure(exc_val)
        return False  # Don't suppress exceptions


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


# Global circuit breakers for different services
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None
) -> CircuitBreaker:
    """Get or create a named circuit breaker.

    Args:
        name: Unique name for the circuit breaker
        config: Optional configuration (only used on first creation)

    Returns:
        CircuitBreaker instance
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, config)
    return _circuit_breakers[name]


# Pre-configured circuit breaker for InsightFace ML inference
insightface_breaker = get_circuit_breaker(
    "insightface",
    CircuitBreakerConfig(
        failure_threshold=5,
        failure_window=60.0,
        recovery_timeout=30.0,
        expected_exceptions=(Exception,)
    )
)
