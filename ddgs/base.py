"""Base class for search engines."""

import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from functools import cached_property
from typing import Any, ClassVar, Generic, Literal, TypeVar

from lxml import html
from lxml.etree import HTMLParser as LHTMLParser

from .http_client import HttpClient
from .proxy import _proxy_rotator
from .results import BooksResult, ImagesResult, NewsResult, TextResult, VideosResult
from .throttle import _throttle

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BaseSearchEngine(ABC, Generic[T]):
    """Abstract base class for all search-engine backends."""

    name: ClassVar[str]  # unique key, e.g. "google"
    category: ClassVar[Literal["text", "images", "videos", "news", "books"]]
    provider: ClassVar[str]  # source of the search results (e.g. "bing" for DuckDuckgo)
    disabled: ClassVar[bool] = False  # if True, the engine is disabled
    priority: ClassVar[float] = 1

    search_url: str
    search_method: ClassVar[str]  # GET or POST
    headers_update: ClassVar[Mapping[str, str]] = {}
    items_xpath: ClassVar[str]
    elements_xpath: ClassVar[Mapping[str, str]]
    elements_replace: ClassVar[Mapping[str, str]]

    def __init__(self, proxy: str | None = None, timeout: int | None = None, *, verify: bool | str = True) -> None:
        self.http_client = HttpClient(proxy=proxy, timeout=timeout, verify=verify)
        self.http_client.update_headers(self.headers_update)
        self.results: list[T] = []

    @property
    def result_type(self) -> type[T]:
        """Get result type based on category."""
        categories = {
            "text": TextResult,
            "images": ImagesResult,
            "videos": VideosResult,
            "news": NewsResult,
            "books": BooksResult,
        }
        return categories[self.category]

    @abstractmethod
    def build_payload(
        self,
        query: str,
        region: str,
        safesearch: str,
        timelimit: str | None,
        page: int,
        **kwargs: str,
    ) -> dict[str, Any]:
        """Build a payload for the search request."""
        raise NotImplementedError

    _max_retries: ClassVar[int] = 2
    _retry_base_delay: ClassVar[float] = 1.0

    _retryable_statuses: ClassVar[set[int]] = {429}

    def request(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        """Make a throttled request with retry on retryable status codes (429, 202)."""
        if _proxy_rotator is not None:
            self.http_client.set_proxy(_proxy_rotator.next())
        _throttle.acquire(self.provider)
        for attempt in range(self._max_retries + 1):
            resp = self.http_client.request(*args, **kwargs)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in self._retryable_statuses and attempt < self._max_retries:
                delay = self._retry_base_delay * (2 ** attempt)
                logger.info("HTTP %d from %s, retrying in %.1fs (attempt %d/%d)",
                            resp.status_code, self.name, delay, attempt + 1, self._max_retries)
                self.http_client.reset_session()
                time.sleep(delay)
                continue
            return None
        return None

    def _raw_request(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        """Make a throttled raw request with retry on retryable status codes, returning the Response object."""
        if _proxy_rotator is not None:
            self.http_client.set_proxy(_proxy_rotator.next())
        _throttle.acquire(self.provider)
        for attempt in range(self._max_retries + 1):
            resp = self.http_client.request(*args, **kwargs)
            if resp.status_code not in self._retryable_statuses or attempt >= self._max_retries:
                return resp
            delay = self._retry_base_delay * (2 ** attempt)
            logger.info("HTTP %d from %s (raw), retrying in %.1fs (attempt %d/%d)",
                        resp.status_code, self.name, delay, attempt + 1, self._max_retries)
            self.http_client.reset_session()
            time.sleep(delay)
        return resp

    @cached_property
    def parser(self) -> LHTMLParser:
        """Get HTML parser."""
        return LHTMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True, collect_ids=False)

    def extract_tree(self, html_text: str) -> html.Element:
        """Extract html tree from html text."""
        return html.fromstring(html_text, parser=self.parser)

    def pre_process_html(self, html_text: str) -> str:
        """Pre-process html_text before extracting results."""
        return html_text

    def extract_results(self, html_text: str) -> list[T]:
        """Extract search results from html text."""
        html_text = self.pre_process_html(html_text)
        tree = self.extract_tree(html_text)
        items = tree.xpath(self.items_xpath)
        results = []
        for item in items:
            result = self.result_type()
            for key, value in self.elements_xpath.items():
                data = " ".join("".join(item.xpath(value)).split())
                result.__setattr__(key, data)
            results.append(result)
        return results

    def post_extract_results(self, results: list[T]) -> list[T]:
        """Post-process search results."""
        return results

    @staticmethod
    def _accept_language_for_region(region: str) -> str:
        """Convert region (e.g., 'us-en') to Accept-Language header value."""
        country, lang = region.lower().split("-")
        return f"{lang}-{country.upper()},{lang};q=0.5"

    def search(
        self,
        query: str,
        region: str = "jp-ja",
        safesearch: str = "moderate",
        timelimit: str | None = None,
        page: int = 1,
        **kwargs: str,
    ) -> list[T] | None:
        """Search the engine."""
        payload = self.build_payload(
            query=query, region=region, safesearch=safesearch, timelimit=timelimit, page=page, **kwargs
        )
        if self.search_method == "GET":
            html_text = self.request(self.search_method, self.search_url, params=payload)
        else:
            html_text = self.request(self.search_method, self.search_url, data=payload)
        if not html_text:
            return None
        results = self.extract_results(html_text)
        return self.post_extract_results(results)
