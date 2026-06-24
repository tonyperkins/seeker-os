"""4-layer dedup pipeline.

Layer 1: URL hash (sha256 of apply_url) — exact, O(1)
Layer 2: Composite key (canonical_source:board:jobid) — exact, O(1)
Layer 3: Content hash (md5 of first 500 chars of normalized JD) — high confidence
Layer 4: Fuzzy match (rapidfuzz on normalized title+company) — medium confidence

See docs/DEDUP_DESIGN.md for full design.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3

from rapidfuzz import fuzz

from seeker_os.dedup.normalize import normalize_company, normalize_title
from seeker_os.models import DedupResult, JobCard


def url_hash(apply_url: str) -> str:
    """SHA256 of the canonical apply URL."""
    normalized = apply_url.lower().rstrip("/")
    return hashlib.sha256(normalized.encode()).hexdigest()


def composite_key(source_job_id: str, source_map: dict[str, str]) -> str | None:
    """Decompose hiring.cafe ID into canonical dedup key.

    source_map is passed in from sources.yml config, not hardcoded.
    """
    from urllib.parse import unquote
    decoded = unquote(source_job_id)
    parts = decoded.split("___")
    if len(parts) != 3:
        return None  # malformed, skip composite key
    hc_source, board_token, job_id = parts
    canonical = source_map.get(hc_source, hc_source)
    return f"{canonical}:{board_token}:{job_id}"


def content_hash(jd_text: str) -> str:
    """MD5 of first 500 chars of normalized JD text."""
    text = re.sub(r"<[^>]+>", "", jd_text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.md5(text[:500].encode()).hexdigest()


def check_duplicate(
    job: JobCard,
    db: sqlite3.Connection,
    source_map: dict[str, str],
    title_threshold: int = 90,
    company_threshold: int = 85,
) -> DedupResult:
    """Run job through all 4 dedup layers.

    Returns on first match. If no match, returns is_duplicate=False.
    """
    # Layer 1: URL hash
    uh = url_hash(job.apply_url)
    row = db.execute("SELECT id FROM jobs WHERE url_hash = ?", (uh,)).fetchone()
    if row:
        return DedupResult(is_duplicate=True, layer="url_hash", matched_job_id=row["id"], confidence="exact")

    # Layer 2: Composite key
    ck = composite_key(job.source_job_id, source_map)
    if ck:
        row = db.execute(
            "SELECT job_id FROM dedup_registry WHERE key_type='composite' AND key_value=?",
            (ck,),
        ).fetchone()
        if row:
            return DedupResult(is_duplicate=True, layer="composite", matched_job_id=row["job_id"], confidence="exact")

    # Layer 3: Content hash (only if JD is available)
    # This runs after JD fetch — check if job has jd_full
    # For card-level dedup (Tier 1), this layer is skipped
    # (called separately after JD fetch)

    # Layer 4: Fuzzy match
    new_title_norm = normalize_title(job.title)
    new_company_norm = normalize_company(job.company)

    # Narrow by company_norm — only scan jobs with similar company
    candidates = db.execute(
        "SELECT id, title_norm, company_norm, commitment FROM jobs WHERE company_norm IS NOT NULL",
    ).fetchall()

    new_commitment = job.commitment[0] if job.commitment else ""

    for row in candidates:
        ex_title = row["title_norm"] or ""
        ex_company = row["company_norm"] or ""
        ex_commitment_str = row["commitment"] or "[]"

        title_score = fuzz.ratio(new_title_norm, ex_title)
        company_score = fuzz.ratio(new_company_norm, ex_company)

        if title_score > title_threshold and company_score > company_threshold:
            # Additional check: same commitment type
            # (don't merge full-time with contract)
            import json
            ex_commitment = json.loads(ex_commitment_str)
            ex_commit = ex_commitment[0] if ex_commitment else ""
            if new_commitment == ex_commit or not new_commitment or not ex_commit:
                return DedupResult(
                    is_duplicate=True,
                    layer="fuzzy",
                    matched_job_id=row["id"],
                    confidence="medium",
                )

    return DedupResult(is_duplicate=False)


def check_content_duplicate(
    job_id: int,
    jd_text: str,
    db: sqlite3.Connection,
) -> DedupResult:
    """Check content hash after JD fetch (Layer 3).

    Returns DedupResult. If a match is found, the job is a likely repost.
    """
    ch = content_hash(jd_text)
    row = db.execute(
        "SELECT job_id FROM dedup_registry WHERE key_type='content_hash' AND key_value=? AND job_id != ?",
        (ch, job_id),
    ).fetchone()
    if row:
        return DedupResult(is_duplicate=True, layer="content_hash", matched_job_id=row["job_id"], confidence="high")
    return DedupResult(is_duplicate=False)


def register_keys(
    job_id: int,
    job: JobCard,
    db: sqlite3.Connection,
    source_map: dict[str, str],
) -> None:
    """Register dedup keys for a new job after insert.

    Registers composite key in dedup_registry (url_hash is in jobs table via UNIQUE).
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    # Register composite key
    ck = composite_key(job.source_job_id, source_map)
    if ck:
        db.execute(
            "INSERT INTO dedup_registry (job_id, key_type, key_value, created_at) VALUES (?, 'composite', ?, ?)",
            (job_id, ck, now),
        )

    # Update normalized fields for fuzzy matching
    db.execute(
        "UPDATE jobs SET title_norm=?, company_norm=? WHERE id=?",
        (normalize_title(job.title), normalize_company(job.company), job_id),
    )


def register_content_hash(job_id: int, jd_text: str, db: sqlite3.Connection) -> None:
    """Register content hash after JD fetch."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    ch = content_hash(jd_text)

    db.execute(
        "INSERT INTO dedup_registry (job_id, key_type, key_value, created_at) VALUES (?, 'content_hash', ?, ?)",
        (job_id, ch, now),
    )
    db.execute("UPDATE jobs SET content_hash=? WHERE id=?", (ch, job_id))
