"""Per-provider request throttling."""

import logging
import threading
import time
from random import uniform

logger = logging.getLogger(__name__)


class ProviderThrottle:
    """Thread-safe per-provider request rate limiter.

    Tracks the last request time for each provider name and enforces
    a minimum interval between consecutive requests to the same provider.

    Attributes:
        min_interval: Minimum seconds between requests to the same provider.
            Set to 0 or negative to disable throttling.
        jitter: Fraction of min_interval to add as random variation.
            For example, 0.3 means ±30% jitter. Set to 0 for exact intervals.

    """

    __slots__ = ("_jitter", "_last_request", "_lock", "_min_interval")

    def __init__(self, *, min_interval: float = 0, jitter: float = 0) -> None:
        self._min_interval = min_interval
        self._jitter = jitter
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    @property
    def min_interval(self) -> float:
        """Get the minimum interval between requests."""
        return self._min_interval

    @min_interval.setter
    def min_interval(self, value: float) -> None:
        """Set the minimum interval between requests."""
        self._min_interval = value

    @property
    def jitter(self) -> float:
        """Get the jitter factor."""
        return self._jitter

    @jitter.setter
    def jitter(self, value: float) -> None:
        """Set the jitter factor."""
        self._jitter = value

    def acquire(self, provider: str) -> None:
        """Block until min_interval has elapsed since the last request to this provider.

        Uses a reserve-then-sleep pattern: the timestamp slot is reserved atomically
        under a global lock, then the actual sleep happens outside it. This ensures
        different providers are not blocked by each other.

        When jitter is enabled, a random variation is applied to the wait time
        to make the request pattern less predictable.

        Args:
            provider: The provider name string (e.g. "bing", "brave").

        """
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(provider, 0.0)
            wait_time = max(0.0, self._min_interval - (now - last))
            if self._jitter > 0 and wait_time > 0:
                jitter_range = wait_time * self._jitter
                wait_time = max(0.0, wait_time + uniform(-jitter_range, jitter_range))  # noqa: S311
            self._last_request[provider] = now + wait_time
        if wait_time > 0:
            logger.debug("Throttling provider %s: sleeping %.3fs", provider, wait_time)
            time.sleep(wait_time)

    def reset(self, provider: str | None = None) -> None:
        """Reset throttle state for a specific provider or all providers.

        Args:
            provider: If provided, reset only this provider. Otherwise reset all.

        """
        with self._lock:
            if provider:
                self._last_request.pop(provider, None)
            else:
                self._last_request.clear()


_throttle = ProviderThrottle()
