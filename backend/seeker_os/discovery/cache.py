"""Simple file-based HTTP response cache."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path


class DiskCache:
    """File-based cache for HTTP responses.

    Stores responses as files in a cache directory. Each entry has a TTL.
    Key is hashed to a filename. Used to avoid re-fetching within a run.
    """

    def __init__(self, cache_dir: str | Path, ttl_hours: int = 6):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_hours * 3600

    def _path(self, key: str) -> Path:
        """Hash the key to a safe filename."""
        hashed = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.cache_dir / f"{hashed}.cache"

    def get(self, key: str) -> str | None:
        """Return cached response if not expired, else None."""
        path = self._path(key)
        if not path.exists():
            return None

        # Check TTL: file mtime vs now
        mtime = path.stat().st_mtime
        if time.time() - mtime > self.ttl_seconds:
            return None

        return path.read_text(encoding="utf-8")

    def set(self, key: str, content: str) -> None:
        """Cache a response."""
        path = self._path(key)
        path.write_text(content, encoding="utf-8")

    def clear_expired(self) -> int:
        """Remove expired entries. Returns count of removed files."""
        removed = 0
        now = time.time()
        for path in self.cache_dir.glob("*.cache"):
            if now - path.stat().st_mtime > self.ttl_seconds:
                path.unlink()
                removed += 1
        return removed

    def clear_all(self) -> int:
        """Remove all cached entries. Returns count of removed files."""
        removed = 0
        for path in self.cache_dir.glob("*.cache"):
            path.unlink()
            removed += 1
        return removed
