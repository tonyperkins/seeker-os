"""Retrieval adapter registry — maps provider type → adapter class, builds instances.

Mirrors discovery/sources/registry.py. New providers register here.
"""

from __future__ import annotations

import logging

from seeker_os.research.retrieval.base import RetrievalAdapter
from seeker_os.research.retrieval.tavily import TavilyAdapter

logger = logging.getLogger(__name__)

_ADAPTER_CLASSES: dict[str, type] = {
    "tavily": TavilyAdapter,
}


def build_retrieval_adapter(config: dict) -> RetrievalAdapter | None:
    """Build a retrieval adapter from a config dict.

    The config dict comes from the 'retrieval' section of company_research.yml.
    It must contain:
      - type: adapter type (e.g. 'tavily')
      - api_key: API key (env var references are already resolved by Settings)

    Returns None if the adapter type is unknown or the config is missing.
    """
    if not config:
        return None

    adapter_type = config.get("type", "")
    if not adapter_type:
        return None

    adapter_cls = _ADAPTER_CLASSES.get(adapter_type)
    if adapter_cls is None:
        logger.warning(
            "Unknown retrieval adapter type '%s' — skipping. "
            "Registered types: %s",
            adapter_type,
            list(_ADAPTER_CLASSES.keys()),
        )
        return None

    api_key = config.get("api_key", "")
    if not api_key:
        logger.warning(
            "Retrieval adapter '%s' has no api_key — retrieval disabled",
            adapter_type,
        )
        return None

    max_results = config.get("max_results", 5)
    timeout = config.get("timeout_seconds", 15)

    return adapter_cls(
        api_key=api_key,
        max_results=max_results,
        timeout=timeout,
    )
