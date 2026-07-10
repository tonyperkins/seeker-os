"""Tavily retrieval adapter — web search API.

Tavily is one retrieval provider. Provider choice and API key come from
config/env, never hardcoded. See retrieval/base.py for the interface.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from seeker_os.research.retrieval.models import RetrievalSnippet

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyAdapter:
    """Tavily web search adapter.

    Implements the RetrievalAdapter protocol. All provider-specific logic
    is encapsulated here — the research flow never sees Tavily-specific
    fields.
    """

    def __init__(self, api_key: str, max_results: int = 5, timeout: int = 15):
        self._id = "tavily"
        self._type = "tavily"
        self._api_key = api_key
        self._max_results = max_results
        self._timeout = timeout

    @property
    def id(self) -> str:
        return self._id

    @property
    def type(self) -> str:
        return self._type

    def search(self, query: str, max_results: int | None = None, include_domains: list[str] | None = None) -> list[RetrievalSnippet]:
        """Run a Tavily search query and return snippets with URLs."""
        if not self._api_key:
            logger.warning("Tavily adapter has no API key — returning empty results")
            return []

        limit = max_results or self._max_results
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": limit,
            "include_answer": False,
        }
        if include_domains:
            payload["include_domains"] = include_domains

        try:
            resp = httpx.post(
                TAVILY_SEARCH_URL,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Tavily search failed for query '%s': %s", query, e)
            return []

        results = data.get("results", [])
        snippets: list[RetrievalSnippet] = []
        for r in results:
            url = r.get("url", "")
            if not url:
                continue
            domain = urlparse(url).netloc
            snippets.append(RetrievalSnippet(
                title=r.get("title", ""),
                url=url,
                snippet=r.get("content", ""),
                source_domain=domain,
                score=r.get("score"),
            ))
        return snippets

    def test_connection(self) -> bool:
        """Test that the Tavily API is reachable and the key is valid."""
        if not self._api_key:
            return False
        try:
            self.search("test", max_results=1)
            return True
        except Exception:
            return False
