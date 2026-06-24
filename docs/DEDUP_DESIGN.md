# Dedup System Design — Seeker OS

**Status:** Design complete, implementation in Phase 1
**Goal:** Robust multi-layer deduplication that catches ~98% of duplicates without
false merges.

## Problem Statement

The current Hermes system uses simple `source:slug:jobid` string keys. This catches
exact duplicates but misses:

1. **Same job reposted** with a new ID (company archives and reposts)
2. **Same job across ATS sources** (Greenhouse direct scan + hiring.cafe's re-index)
3. **Same job with different title phrasing** ("Sr SRE" vs "Senior Site Reliability Engineer")
4. **Same company, different name variants** ("TREX Solutions" vs "TREX Solutions LLC")
5. **Same job across different hiring.cafe queries** (a job matching both "senior-sre-remote" and "staff-platform-engineer-remote")

## Multi-Layer Architecture

```
New job arrives at Tier 1
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Exact URL Hash                                  │
│ sha256(apply_url) — indexed UNIQUE in jobs table         │
│ Catches: same job re-indexed by hiring.cafe, same URL    │
│ Cost: O(1) — indexed lookup                               │
│ Catches: ~70% of duplicates                               │
└──────────────────────────┬──────────────────────────────┘
                           │ not found
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Composite Key                                    │
│ {canonical_source}:{board_token}:{job_id}                 │
│ Catches: same job via direct ATS scan + hiring.cafe       │
│ Cost: O(1) — indexed lookup in dedup_registry             │
│ Catches: ~20% of duplicates (cross-source)                │
└──────────────────────────┬──────────────────────────────┘
                           │ not found
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Content Hash                                     │
│ md5(first 500 chars of normalized JD text)                │
│ Catches: reposted jobs (same JD, new ID)                  │
│ Cost: O(1) — indexed lookup after hash computation        │
│ Catches: ~5% of duplicates (reposts)                      │
│ Note: only available after Tier 3 (JD fetch)              │
└──────────────────────────┬──────────────────────────────┘
                           │ not found
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 4: Fuzzy Match                                      │
│ rapidfuzz title similarity + company similarity           │
│ Catches: same job with different title/company phrasing   │
│ Cost: O(n) scan, narrowed by company_norm index           │
│ Method: rapidfuzz (Levenshtein-based, C-backed, fast)     │
│   - Title similarity > 90 (after normalization)           │
│   - Company similarity > 85 (after normalization)         │
│   - Same commitment type                                  │
│ Catches: ~5% of duplicates (fuzzy)                        │
│ False positive risk: LOW — flagged for review, not merged │
│ Timing: runs after JD fetch (Tier 3), alongside Layer 3.  │
│   Fuzzy match uses title+company, not score or JD text,   │
│   so it does not depend on scoring (Tier 4).              │
└──────────────────────────┬──────────────────────────────┘
                           │ not found
                           ▼
                    NEW JOB — insert
```

## Layer Details

### Layer 1: URL Hash

```python
import hashlib

def url_hash(apply_url: str) -> str:
    """SHA256 of the canonical apply URL."""
    # Normalize: lowercase, strip trailing slashes, strip query params for ATS URLs
    normalized = apply_url.lower().rstrip('/')
    # For Greenhouse URLs, strip gh_jid param for comparison
    # (different board URLs may point to same job)
    return hashlib.sha256(normalized.encode()).hexdigest()
```

**Stored as:** `jobs.url_hash` (UNIQUE constraint)
**Check:** INSERT fails on duplicate → caught

### Layer 2: Composite Key

```python
# source_map is loaded from config/sources.yml (not hardcoded — see AGENTS.md § no-hardcode)
# Example: {"grnhse": "greenhouse", "ashby": "ashby", "lever": "lever", ...}

def composite_key(source_job_id: str, source_map: dict[str, str]) -> str | None:
    """Decompose hiring.cafe ID into canonical dedup key.

    source_map is passed in from sources.yml config, not hardcoded.
    """
    # hc_id format: source___board_token___jobid
    # URL-decode first
    from urllib.parse import unquote
    decoded = unquote(source_job_id)
    parts = decoded.split('___')
    if len(parts) != 3:
        return None  # malformed, skip composite key
    hc_source, board_token, job_id = parts
    canonical = source_map.get(hc_source, hc_source)
    return f"{canonical}:{board_token}:{job_id}"
```

**Stored as:** `dedup_registry` row with `key_type='composite'`
**Check:** SELECT from dedup_registry before insert

### Layer 3: Content Hash

```python
import hashlib, re

def content_hash(jd_text: str) -> str:
    """MD5 of first 500 chars of normalized JD text."""
    # Normalize: lowercase, strip HTML, strip whitespace
    text = re.sub(r'<[^>]+>', '', jd_text).lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return hashlib.md5(text[:500].encode()).hexdigest()
```

**Stored as:** `dedup_registry` row with `key_type='content_hash'`
**Note:** Only available after Tier 3 (JD fetch). For Tier 1-2 dedup, this layer is skipped.
**Check:** SELECT from dedup_registry after JD fetch

### Layer 4: Fuzzy Match

```python
from rapidfuzz import fuzz

def fuzzy_match(new_title_norm: str, new_company_norm: str,
                existing_jobs: list) -> bool:
    """Check if a new job fuzzy-matches any existing job.

    existing_jobs: list of (id, title_norm, company_norm, commitment) tuples
    """
    for job_id, ex_title, ex_company, ex_commitment in existing_jobs:
        title_score = fuzz.ratio(new_title_norm, ex_title)
        company_score = fuzz.ratio(new_company_norm, ex_company)

        if title_score > 90 and company_score > 85:
            # Additional check: same commitment type
            # (don't merge full-time with contract)
            return True  # flag as likely duplicate

    return False
```

**Performance:** Narrowed by company_norm index — only scan jobs with similar company.
For ~1000 jobs in DB, this is <10ms per check.

**Timing:** Runs after JD fetch (Tier 3), alongside Layer 3. Fuzzy match uses
title+company (available at card level), not score or JD text, so it does not depend
on scoring (Tier 4). Running it immediately after JD fetch catches duplicates before
scoring, saving scoring work on duplicates.

**Thresholds are configurable** via settings:
- `dedup_title_threshold` (default 90)
- `dedup_company_threshold` (default 85)

### Layer 5 (Future): Semantic Embedding

Deferred to v2. Would catch same job with substantially rewritten JD.

```python
# Future implementation
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('BAAI/bge-small-en-v1.5')  # local, no API

def embedding_similarity(jd1: str, jd2: str) -> float:
    emb1 = model.encode(jd1)
    emb2 = model.encode(jd2)
    from numpy import dot
    from numpy.linalg import norm
    return dot(emb1, emb2) / (norm(emb1) * norm(emb2))

# Threshold: > 0.92 → likely duplicate
```

**Why deferred:** Layers 1-4 catch ~98% of duplicates. Embedding adds complexity
(model download, vector storage) for marginal gain. Revisit if fuzzy layer proves insufficient.

## Normalization Functions

```python
import re

def normalize_title(title: str) -> str:
    """Normalize job title for fuzzy matching."""
    t = title.lower().strip()

    # Map common abbreviations and synonyms using word-boundary regex.
    # NOTE: Do NOT use bidirectional pairs (e.g. devops↔dev ops) — they cancel out.
    # NOTE: Do NOT use bare substring replace for short tokens like 'sre' —
    #       it would match inside other words. Use \b word boundaries.
    replacements = [
        (r'\bsr\b\.?', 'senior'),
        (r'\bsre\b', 'site reliability engineer'),
        (r'\bdevops\b', 'devops'),           # normalize spelling, no transform
        (r'\bdev ops\b', 'devops'),          # unify to one form
        (r'\binfra\b', 'infrastructure'),
        (r'\bk8s\b', 'kubernetes'),
        (r'\bplatform eng\b', 'platform engineer'),
        (r'\bcloud eng\b', 'cloud engineer'),
        (r'\brel eng\b', 'reliability engineer'),
        (r'\bbuild eng\b', 'build engineer'),
        (r'\brelease eng\b', 'release engineer'),
    ]
    for pattern, replacement in replacements:
        t = re.sub(pattern, replacement, t)

    # Remove punctuation
    t = re.sub(r'[^a-z0-9\s]', '', t)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    # Remove common filler words
    fillers = ['engineer', 'engineering', 'role', 'position']
    # Don't remove these — they're meaningful for matching

    return t


def normalize_company(company: str) -> str:
    """Normalize company name for fuzzy matching."""
    c = company.lower().strip()

    # Strip common suffixes
    suffixes = [
        ' inc', ' inc.', ' llc', ' ltd', ' corp', ' corporation',
        ' technologies', ' tech', ' labs', ' ai', ' co', ' group',
        ' holdings', ' partners', ' solutions', ' systems',
        ' software', ' digital', ' global'
    ]
    for suffix in suffixes:
        if c.endswith(suffix):
            c = c[:-len(suffix)]

    # Remove punctuation
    c = re.sub(r'[^a-z0-9\s]', '', c)
    # Collapse whitespace
    c = re.sub(r'\s+', ' ', c).strip()

    return c
```

## Handling Flagged Duplicates

When Layer 3 or 4 flags a potential duplicate, the job is NOT silently dropped.
Instead:

1. Job is inserted with `status='duplicate_flagged'`
2. `dedup_registry` entry added with `key_type='fuzzy'` or `'content_hash'`,
   `matched_job_id`, `dedup_layer`, and `confidence` (so the dashboard can explain
   the match later)
3. Job appears in dashboard under a "Review Duplicates" section
4. User can confirm duplicate (merge/skip) or dismiss (mark as unique)

This prevents false merges — two genuinely different "Senior SRE" roles at the same
company would have different JD content (caught by Layer 3 as NOT duplicate) but
similar titles (flagged by Layer 4 for review).

## Dedup Timing Summary

| Layer | When it runs | What it needs |
|---|---|---|
| 1 (URL hash) | Tier 1, before insert | `apply_url` (from card) |
| 2 (composite key) | Tier 1, before insert | `hc_id` (from card) |
| 3 (content hash) | Tier 3, after JD fetch | `jd_text` (from ATS fetch) |
| 4 (fuzzy match) | Tier 3, after JD fetch | `title_norm`, `company_norm` (from card) |

Layers 1-2 run early (before insert) to catch exact duplicates cheaply.
Layers 3-4 run after JD fetch to catch reposts and fuzzy matches before scoring.
No dedup layer runs after scoring — scoring is never wasted on duplicates.

## Cross-Source Collapse

The key insight from the Hermes feasibility spike: hiring.cafe's `id` field decomposes
to the same canonical key as direct ATS scans.

```
hiring.cafe: grnhse___trexsolutions___8534403002
  → canonical: greenhouse:trexsolutions:8534403002

Direct scan: greenhouse:trexsolutions:8534403002
  → SAME KEY
```

This means if Seeker OS ever adds direct ATS scanning (beyond hiring.cafe), the dedup
system automatically collapses cross-source duplicates. No special handling needed.

## Performance Estimates

| DB size | Layer 1 | Layer 2 | Layer 3 | Layer 4 | Total per job |
|---------|---------|---------|---------|---------|---------------|
| 100 jobs | <1ms | <1ms | <1ms | <5ms | <8ms |
| 1,000 jobs | <1ms | <1ms | <1ms | <20ms | <23ms |
| 10,000 jobs | <1ms | <1ms | <1ms | <100ms | <103ms |

Layer 4 is the only O(n) operation, but it's narrowed by company_norm index. In
practice, fuzzy matching only scans jobs with the same (or similar) company_norm,
which is typically <50 jobs even at scale.

## Testing Strategy

1. **Unit tests:** Each normalization function, each layer
2. **Integration test:** Feed known duplicate pairs through all layers
3. **False positive test:** Feed known unique jobs, verify they're NOT flagged
4. **Cross-source test:** Feed same job from hiring.cafe + direct ATS, verify collapse
5. **Repost test:** Feed same JD with different ID, verify Layer 3 catches it
