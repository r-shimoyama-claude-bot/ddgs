"""HTTP client."""

import logging
from collections.abc import Mapping
from typing import Any

import primp

from .exceptions import DDGSException, TimeoutException

logger = logging.getLogger(__name__)


class Response:
    """HTTP response."""

    __slots__ = ("_resp", "content", "status_code", "text")

    def __init__(self, resp: Any) -> None:  # noqa: ANN401
        self._resp = resp
        self.status_code = resp.status_code
        self.content = resp.content
        self.text = resp.text

    @property
    def text_markdown(self) -> str:
        """Get response body as Markdown text."""
        return self._resp.text_markdown  # type: ignore[no-any-return]

    @property
    def text_plain(self) -> str:
        """Get response body as plain text."""
        return self._resp.text_plain  # type: ignore[no-any-return]

    @property
    def text_rich(self) -> str:
        """Get response body as rich text."""
        return self._resp.text_rich  # type: ignore[no-any-return]


class HttpClient:
    """HTTP client with proxy rotation support."""

    def __init__(self, proxy: str | None = None, timeout: int | None = 10, *, verify: bool | str = True) -> None:
        """Initialize the HttpClient object.

        Args:
            proxy: proxy for the HTTP client, supports http/https/socks5 protocols.
                example: "http://user:pass@example.com:3128". Defaults to None.
            timeout: Timeout value for the HTTP client. Defaults to 10.
            verify: True to verify, False to skip, or a str path to a PEM file. Defaults to True.

        """
        self._timeout = timeout
        self._verify = verify
        self._proxy = proxy
        self._custom_headers: dict[str, str] = {}
        self.client = self._build_client(proxy)

    def _build_client(self, proxy: str | None) -> primp.Client:
        """Build a primp.Client with the given proxy and stored settings."""
        client = primp.Client(
            proxy=proxy,
            timeout=self._timeout,
            impersonate="random",
            impersonate_os="random",
            verify=self._verify if isinstance(self._verify, bool) else True,
            ca_cert_file=self._verify if isinstance(self._verify, str) else None,
        )
        if self._custom_headers:
            client.headers_update(self._custom_headers)
        return client

    def set_proxy(self, proxy: str | None) -> None:
        """Switch to a different proxy by rebuilding the underlying client.

        Custom headers are preserved.

        Args:
            proxy: The new proxy URL, or None for no proxy.

        """
        self._proxy = proxy
        self.client = self._build_client(proxy)

    def reset_session(self) -> None:
        """Reset the HTTP session to get fresh cookies and TLS state."""
        self.client = self._build_client(self._proxy)

    def update_headers(self, headers: Mapping[str, str]) -> None:
        """Update HTTP headers on the underlying client.

        Headers are stored internally so they persist across proxy changes.

        Args:
            headers: Mapping of header names to values.

        """
        self._custom_headers.update(headers)
        self.client.headers_update(headers)

    def request(self, *args: Any, **kwargs: Any) -> Response:  # noqa: ANN401
        """Make a request to the HTTP client."""
        try:
            resp = self.client.request(*args, **kwargs)
            return Response(resp)
        except primp.TimeoutError as ex:
            raise TimeoutException(ex) from ex
        except Exception as ex:
            msg = f"{type(ex).__name__}: {ex!r}"
            raise DDGSException(msg) from ex

    def get(self, url: str, *args: Any, **kwargs: Any) -> Response:  # noqa: ANN401
        """Make a GET request to the HTTP client."""
        return self.request("GET", url, *args, **kwargs)

    def post(self, url: str, *args: Any, **kwargs: Any) -> Response:  # noqa: ANN401
        """Make a POST request to the HTTP client."""
        return self.request("POST", url, *args, **kwargs)
