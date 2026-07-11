"""Model cache — caches auto-fetched model lists to disk.

Cache files are stored as JSON in data/cache/models/{provider_id}.json
Cache TTL: 24 hours (configurable).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seeker_os.llm.models import ModelInfo

CACHE_DIR = Path("data/cache/models")
CACHE_TTL_HOURS = 24


def _cache_path(provider_id: str) -> Path:
    return CACHE_DIR / f"{provider_id}.json"


def get_cached_models(provider_id: str) -> list[ModelInfo] | None:
    """Get cached models for a provider, or None if cache is stale/missing."""
    path = _cache_path(provider_id)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now(UTC) - fetched_at > timedelta(hours=CACHE_TTL_HOURS):
            return None  # stale

        return [
            ModelInfo(
                id=m["id"],
                label=m["label"],
                provider_id=m["provider_id"],
                context_window=m.get("context_window"),
                max_output=m.get("max_output"),
                tags=m.get("tags", []),
                source=m.get("source", "auto"),
                available=m.get("available", True),
                fetched_at=m.get("fetched_at"),
                input_price_per_mtok=m.get("input_price_per_mtok"),
                output_price_per_mtok=m.get("output_price_per_mtok"),
                pricing_source=m.get("pricing_source"),
            )
            for m in data["models"]
        ]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def get_cached_pricing(provider_id: str) -> dict[str, tuple[float | None, float | None]]:
    """Get pricing for all cached models for a provider, ignoring TTL staleness.

    Pricing data doesn't go stale the way model availability does, so this is
    safe to use for cost estimation even when the model list cache is stale.
    Returns a dict mapping model_id → (input_price_per_mtok, output_price_per_mtok).
    """
    path = _cache_path(provider_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {
            m["id"]: (m.get("input_price_per_mtok"), m.get("output_price_per_mtok"))
            for m in data["models"]
        }
    except (json.JSONDecodeError, KeyError, ValueError):
        return {}


def save_cached_models(provider_id: str, models: list[ModelInfo]) -> None:
    """Save models to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(provider_id)
    now = datetime.now(UTC).isoformat()

    data = {
        "provider_id": provider_id,
        "fetched_at": now,
        "models": [
            {
                "id": m.id,
                "label": m.label,
                "provider_id": m.provider_id,
                "context_window": m.context_window,
                "max_output": m.max_output,
                "tags": m.tags,
                "source": m.source,
                "available": m.available,
                "fetched_at": m.fetched_at,
                "input_price_per_mtok": m.input_price_per_mtok,
                "output_price_per_mtok": m.output_price_per_mtok,
                "pricing_source": m.pricing_source,
            }
            for m in models
        ],
    }
    path.write_text(json.dumps(data, indent=2))


def clear_cache(provider_id: str | None = None) -> None:
    """Clear cache for a provider, or all caches if None."""
    if provider_id:
        path = _cache_path(provider_id)
        if path.exists():
            path.unlink()
    else:
        if CACHE_DIR.exists():
            for f in CACHE_DIR.glob("*.json"):
                f.unlink()
