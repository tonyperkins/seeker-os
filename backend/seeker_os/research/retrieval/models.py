"""Pydantic models for retrieval adapter results."""

from __future__ import annotations

from pydantic import BaseModel


class RetrievalSnippet(BaseModel):
    """A single search result from a retrieval adapter.

    Each snippet carries the text and the source URL so the LLM can attach
    URLs to claims. No URL = unusable for sourced claims.
    """
    title: str = ""
    url: str = ""
    snippet: str = ""
    source_domain: str = ""
    published_date: str | None = None
    score: float | None = None
