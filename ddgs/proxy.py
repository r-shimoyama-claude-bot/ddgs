"""Proxy rotation for distributing requests across multiple proxies."""

import logging
import threading

logger = logging.getLogger(__name__)


class ProxyRotator:
    """Thread-safe round-robin proxy rotator.

    Cycles through a list of proxy URLs, returning the next one on each call.
    When only one proxy is configured, returns it without rotation overhead.

    Attributes:
        proxies: The list of proxy URLs (None entries mean no proxy).

    """

    __slots__ = ("_index", "_lock", "_proxies")

    def __init__(self, proxies: list[str | None]) -> None:
        self._proxies = proxies
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> str | None:
        """Return the next proxy in round-robin order.

        Returns:
            The next proxy URL, or None if no proxy is configured.

        """
        if len(self._proxies) <= 1:
            return self._proxies[0] if self._proxies else None
        with self._lock:
            proxy = self._proxies[self._index]
            self._index = (self._index + 1) % len(self._proxies)
        return proxy


def set_proxy_rotator(rotator: ProxyRotator | None) -> None:
    """Set the module-level proxy rotator singleton."""
    global _proxy_rotator  # noqa: PLW0603
    _proxy_rotator = rotator


_proxy_rotator: ProxyRotator | None = None
