"""
In-memory, thread-safe cache with TTL for the Model League API response.
"""
import threading
import time
from typing import Any, Callable, Optional


class LeagueCache:
    """Thread-safe in-memory cache for the League response with a 5-minute default TTL."""

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._cached_value: Optional[Any] = None
        self._cached_at: Optional[float] = None

    @property
    def clock(self) -> Callable[[], float]:
        return self._clock

    @clock.setter
    def clock(self, fn: Callable[[], float]) -> None:
        with self._lock:
            self._clock = fn

    def get(self) -> Optional[Any]:
        with self._lock:
            if self._cached_value is None or self._cached_at is None:
                return None
            if (self._clock() - self._cached_at) >= self.ttl_seconds:
                self._cached_value = None
                self._cached_at = None
                return None
            return self._cached_value

    def set(self, value: Any) -> None:
        with self._lock:
            self._cached_value = value
            self._cached_at = self._clock()

    def get_or_compute(self, compute_fn: Callable[[], Any]) -> Any:
        with self._lock:
            now = self._clock()
            if self._cached_value is not None and self._cached_at is not None:
                if (now - self._cached_at) < self.ttl_seconds:
                    return self._cached_value
            result = compute_fn()
            self._cached_value = result
            self._cached_at = now
            return result

    def clear(self) -> None:
        with self._lock:
            self._cached_value = None
            self._cached_at = None
