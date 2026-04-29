"""DuckDuckGo Lite search engine implementation."""

import os
from typing import Any, ClassVar

from lxml import html as lxml_html

from ddgs.base import BaseSearchEngine
from ddgs.results import TextResult


class DuckduckgoLite(BaseSearchEngine[TextResult]):
    """DuckDuckGo Lite search engine (alternative endpoint to avoid bot detection)."""

    name = "duckduckgo_lite"
    category = "text"
    provider = "duckduckgo_lite"

    _retryable_statuses: ClassVar[set[int]] = {429, 202}
    _retry_base_delay: ClassVar[float] = float(os.environ.get("DDGS_RETRY_DELAY", "3.0"))
    _max_retries: ClassVar[int] = int(os.environ.get("DDGS_MAX_RETRIES", "3"))

    search_url = "https://lite.duckduckgo.com/lite/"
    search_method = "POST"

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
        payload: dict[str, Any] = {"q": query, "kl": region}
        if page > 1:
            payload["s"] = f"{(page - 1) * 20}"
        if timelimit:
            payload["df"] = timelimit
        return payload

    def search(
        self,
        query: str,
        region: str = "jp-ja",
        safesearch: str = "moderate",
        timelimit: str | None = None,
        page: int = 1,
        **kwargs: str,
    ) -> list[TextResult] | None:
        """Search with Accept-Language header set from region."""
        self.http_client.update_headers({"Accept-Language": self._accept_language_for_region(region)})
        return super().search(query, region, safesearch, timelimit, page, **kwargs)

    def extract_results(self, html_text: str) -> list[TextResult]:
        """Extract search results from lite HTML (table-based layout)."""
        tree = lxml_html.fromstring(html_text, parser=self.parser)
        results: list[TextResult] = []

        link_elements = tree.xpath("//a[contains(@class, 'result-link')]")
        for link_el in link_elements:
            title = " ".join("".join(link_el.xpath(".//text()")).split())
            href = link_el.get("href", "")
            if not title or not href:
                continue

            # Snippet is in the next <tr> sibling's <td class="result-snippet">
            body = ""
            tr_parent = link_el.getparent()
            while tr_parent is not None and tr_parent.tag != "tr":
                tr_parent = tr_parent.getparent()
            if tr_parent is not None:
                next_tr = tr_parent.getnext()
                if next_tr is not None:
                    snippet_tds = next_tr.xpath(".//td[contains(@class, 'result-snippet')]")
                    if snippet_tds:
                        body = " ".join("".join(snippet_tds[0].xpath(".//text()")).split())

            result = TextResult()
            result.title = title
            result.href = href
            result.body = body
            results.append(result)

        return results
