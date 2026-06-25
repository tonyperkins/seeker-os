"""Retrieval adapter interface — pluggable web search for company research.

Mirrors the source-adapter pattern in discovery/sources/. Each provider
(Tavily, SerpAPI, Brave, etc.) implements this interface. Provider choice
and credentials come from config/env, never hardcoded.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seeker_os.research.retrieval.models import RetrievalSnippet


@runtime_checkable
class RetrievalAdapter(Protocol):
    """Abstract retrieval adapter for web search queries."""

    @property
    def id(self) -> str:
        """Adapter identifier (e.g. 'tavily')."""
        ...

    @property
    def type(self) -> str:
        """Adapter type (e.g. 'tavily', 'serpapi', 'brave')."""
        ...

    def search(self, query: str, max_results: int = 5) -> list[RetrievalSnippet]:
        """Run a search query and return snippets with URLs.

        Returns a list of RetrievalSnippet, each carrying a URL. If the
        adapter fails or returns no results, returns an empty list.
        """
        ...

    def test_connection(self) -> bool:
        """Test that the provider is reachable and configured correctly."""
        ...
