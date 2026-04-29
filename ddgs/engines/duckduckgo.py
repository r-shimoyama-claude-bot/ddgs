"""Duckduckgo search engine implementation."""

import os
from collections.abc import Mapping
from typing import Any, ClassVar

from ddgs.base import BaseSearchEngine
from ddgs.results import TextResult


class Duckduckgo(BaseSearchEngine[TextResult]):
    """Duckduckgo search engine."""

    name = "duckduckgo"
    category = "text"
    provider = "bing"

    _retryable_statuses: ClassVar[set[int]] = {429, 202}
    _retry_base_delay: ClassVar[float] = float(os.environ.get("DDGS_RETRY_DELAY", "3.0"))
    _max_retries: ClassVar[int] = int(os.environ.get("DDGS_MAX_RETRIES", "3"))

    search_url = "https://html.duckduckgo.com/html/"
    search_method = "GET"

    items_xpath = "//div[contains(@class, 'body')]"
    elements_xpath: ClassVar[Mapping[str, str]] = {"title": ".//h2//text()", "href": "./a/@href", "body": "./a//text()"}

    def build_payload(
        self,
        query: str,
        region: str,
        safesearch: str,  # noqa: ARG002
        timelimit: str | None,
        page: int = 1,
        **kwargs: str,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Build a payload for the search request."""
        payload: dict[str, Any] = {"q": query, "l": region}
        if page > 1:
            payload["s"] = f"{10 + (page - 2) * 15}"
        if timelimit:
            payload["df"] = timelimit
        return payload

    def search(
        self,
        query: str,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: str | None = None,
        page: int = 1,
        **kwargs: str,
    ) -> list[TextResult] | None:
        """Search with Accept-Language header set from region."""
        self.http_client.update_headers({"Accept-Language": self._accept_language_for_region(region)})
        return super().search(query, region, safesearch, timelimit, page, **kwargs)

    def post_extract_results(self, results: list[TextResult]) -> list[TextResult]:
        """Post-process search results."""
        return [r for r in results if not r.href.startswith("https://duckduckgo.com/y.js?")]
