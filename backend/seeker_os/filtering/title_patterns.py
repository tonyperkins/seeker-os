"""Title matching — positive/negative pattern matching for Tier 2 filtering."""

from __future__ import annotations


def title_matches(title: str, positive: list[str], negative: list[str]) -> bool:
    """Check if title matches any positive pattern AND no negative pattern.

    Case-insensitive substring matching.
    Returns True if positive match found and no negative match.
    If positive is empty, skips positive matching (returns True unless negative matches).
    """
    title_lower = title.lower()

    if positive:
        has_positive = any(p in title_lower for p in positive)
        if not has_positive:
            return False

    has_negative = any(n in title_lower for n in negative)
    return not has_negative
