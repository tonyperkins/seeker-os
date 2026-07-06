"""Adapter registry — maps source type → adapter class, builds adapter instances."""

from __future__ import annotations

from seeker_os.config import SourcesConfig
from seeker_os.discovery.cache import DiskCache
from seeker_os.discovery.sources.base import SourceAdapter
from seeker_os.discovery.sources.hiring_cafe import HiringCafeAdapter

# Type → class mapping. Future adapters register here.
_ADAPTER_CLASSES: dict[str, type[SourceAdapter]] = {
    "hiring_cafe": HiringCafeAdapter,
}


def build_adapters(
    sources_config: SourcesConfig,
    cache: DiskCache,
) -> dict[str, SourceAdapter]:
    """Build adapter instances from sources.yml config.

    Only enabled sources are included. Returns {source_id: adapter_instance}.
    """
    adapters: dict[str, SourceAdapter] = {}
    for src in sources_config.sources:
        if not src.enabled:
            continue
        adapter_cls = _ADAPTER_CLASSES.get(src.type)
        if adapter_cls is None:
            print(f"  WARNING: Unknown source type '{src.type}' for source '{src.id}' — skipping")
            continue
        adapters[src.id] = adapter_cls(src, cache)
    return adapters
