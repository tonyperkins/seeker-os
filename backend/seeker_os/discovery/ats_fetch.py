"""Tier 3: Full JD fetch from ATS APIs or apply_url HTML.

Routes by ats_source:
  - greenhouse: GET boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}
  - ashby: GET api.ashbyhq.com/posting-api/job-board/{board}
  - lever: GET api.lever.co/v0/postings/{board}
  - other: GET apply_url, extract text from HTML

See docs/PHASE1_SPEC.md §3.3 for the full spec.
"""

from __future__ import annotations

import re
import time
import httpx

from seeker_os.models import JDFetchResult


def _strip_html(html: str) -> str:
    """Strip HTML tags, decode entities, normalize whitespace."""
    # Remove script and style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common HTML entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_url(url: str, user_agent: str, timeout: int = 15) -> str:
    """Fetch a URL and return the response text."""
    headers = {"User-Agent": user_agent}
    resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _fetch_greenhouse(board: str, job_id: str, user_agent: str) -> str:
    """Fetch JD from Greenhouse API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    import json
    text = _fetch_url(url, user_agent)
    data = json.loads(text)
    # Greenhouse returns JSON with 'content' field containing HTML
    content = data.get("content", "")
    if not content:
        # Try first_content
        content = data.get("first_content", "")
    return _strip_html(content) if content else ""


def _fetch_ashby(board: str, user_agent: str) -> str:
    """Fetch JD from Ashby API (board-level, then find job)."""
    # Ashby's API is board-level; we'd need to find the specific job.
    # For Phase 1, fall back to apply_url HTML fetch.
    raise NotImplementedError("Ashby API fetch — falling back to apply_url")


def _fetch_lever(board: str, user_agent: str) -> str:
    """Fetch JD from Lever API."""
    # Lever's posting API is board-level
    raise NotImplementedError("Lever API fetch — falling back to apply_url")


def fetch_jd(
    job_id: int,
    ats_source: str | None,
    ats_board_token: str | None,
    ats_job_id: str | None,
    apply_url: str,
    user_agent: str = "Mozilla/5.0",
    delay: float = 2.0,
) -> JDFetchResult:
    """Fetch full JD for a single job.

    Route by ats_source. Strip HTML tags, decode entities, normalize whitespace.
    If fetch fails: return status='failed' with error message.
    """
    time.sleep(delay)  # human-like delay

    try:
        if ats_source == "greenhouse" and ats_board_token and ats_job_id:
            jd_text = _fetch_greenhouse(ats_board_token, ats_job_id, user_agent)
            return JDFetchResult(job_id=job_id, jd_text=jd_text, status="fetched", source_used="greenhouse_api")

        # For all other ATS sources (or API failures), fall back to apply_url HTML
        html = _fetch_url(apply_url, user_agent)
        jd_text = _strip_html(html)

        if not jd_text or len(jd_text) < 100:
            return JDFetchResult(
                job_id=job_id, jd_text="", status="failed",
                source_used="apply_url", error="Extracted text too short or empty",
            )

        return JDFetchResult(
            job_id=job_id, jd_text=jd_text, status="fetched",
            source_used=f"apply_url ({ats_source or 'unknown'})",
        )

    except Exception as e:
        return JDFetchResult(
            job_id=job_id, jd_text="", status="failed",
            source_used=ats_source or "apply_url", error=str(e),
        )
