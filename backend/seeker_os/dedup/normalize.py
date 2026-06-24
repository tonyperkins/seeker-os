"""Title and company normalization for fuzzy dedup matching.

See docs/DEDUP_DESIGN.md § Normalization Functions for the canonical implementation.
Key points (don't repeat the bugs from earlier drafts):
- normalize_title uses \\b word-boundary regex, NOT bare substring replace
- No bidirectional pairs (devops↔dev ops self-cancel with dict iteration)
- normalize_company uses slicing (c[:-len(suffix)]), NOT rstrip (strips char set)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

_TITLE_ABBREVIATIONS: dict[str, str] = {
    "sr": "senior",
    "jr": "junior",
    "sre": "site reliability engineer",
    "devops": "devops",
    "dev ops": "devops",
    "devsecops": "devsecops",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "eng": "engineer",
    "engr": "engineer",
    "sw": "software",
    "swe": "software engineer",
    "se": "software engineer",
    "vp": "vice president",
    "cto": "chief technology officer",
    "infra": "infrastructure",
    "k8s": "kubernetes",
    "aws": "amazon web services",
    "gcp": "google cloud platform",
}

_TITLE_NOISE_WORDS: set[str] = {
    "the", "a", "an", "and", "or", "of", "in", "at", "for", "with",
    "to", "on", "by", "is", "are",
}


def normalize_title(title: str) -> str:
    """Normalize job title for fuzzy matching.

    Steps:
    1. Lowercase
    2. Replace abbreviations (using word-boundary regex, not substring)
    3. Remove punctuation
    4. Remove noise words
    5. Collapse whitespace
    """
    t = title.lower().strip()

    # Replace abbreviations using word boundaries (NOT bare substring replace)
    for abbr, full in _TITLE_ABBREVIATIONS.items():
        # Skip identity mappings (devops -> devops)
        if abbr == full:
            continue
        t = re.sub(rf"\b{re.escape(abbr)}\b", full, t)

    # Remove punctuation (keep alphanumerics and spaces)
    t = re.sub(r"[^a-z0-9\s]", " ", t)

    # Remove noise words
    words = [w for w in t.split() if w not in _TITLE_NOISE_WORDS]

    # Collapse whitespace
    return " ".join(words).strip()


# ---------------------------------------------------------------------------
# Company normalization
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES: list[str] = [
    " inc", " inc.", " llc", " ltd", " ltd.", " corp", " corporation",
    " co", " company",
    " technologies", " technology", " tech",
    " labs", " lab", " ai",
    " group", " holdings", " partners", " solutions",
    " systems", " software", " digital", " global",
    " services", " consulting",
    " usa", " us", " america",
]


def normalize_company(company: str) -> str:
    """Normalize company name for fuzzy matching.

    Steps:
    1. Lowercase
    2. Strip common suffixes (using slicing, NOT rstrip — rstrip strips a char set)
    3. Remove punctuation
    4. Collapse whitespace
    """
    c = company.lower().strip()

    # Strip common suffixes (only strip ONE suffix — use slicing, not rstrip)
    for suffix in _COMPANY_SUFFIXES:
        if c.endswith(suffix):
            c = c[: -len(suffix)]
            break  # only strip one suffix

    # Remove punctuation
    c = re.sub(r"[^a-z0-9\s]", " ", c)

    # Collapse whitespace
    c = re.sub(r"\s+", " ", c).strip()

    return c
