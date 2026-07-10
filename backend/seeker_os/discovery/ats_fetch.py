"""Tier 3: Full JD fetch from ATS APIs or apply_url HTML.

Routes by ats_source:
  - greenhouse: GET boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}
  - ashby: GET api.ashbyhq.com/posting-api/job-board/{board}
  - lever: GET api.lever.co/v0/postings/{board}
  - other: GET apply_url, extract text from HTML
"""

from __future__ import annotations

import re
import time

import httpx

from seeker_os.models import JDFetchResult


def parse_greenhouse_url(url: str) -> tuple[str, str] | None:
    """Parse a Greenhouse job board URL to extract (board, job_id).

    Supports:
      - https://job-boards.greenhouse.io/{board}/jobs/{job_id}
      - https://boards.greenhouse.io/{board}/jobs/{job_id}
    """
    m = re.match(
        r"https?://(?:job-boards\.|boards\.)greenhouse\.io/([^/]+)/jobs/(\d+)",
        url,
    )
    if m:
        return m.group(1), m.group(2)
    return None


def _strip_html(html: str) -> str:
    """Strip HTML to text while preserving block structure as line breaks.

    A flat tag-strip collapses lists and headings onto a single line, which
    degrades the JD text fed to scoring/generation. This converts block-element
    boundaries (<br>, </p>, headings, list items, table rows, …) to newlines and
    bullets list items, so the JD's structure survives. Whitespace is normalized
    per line but newlines are preserved.
    """
    import html as html_mod
    if not html:
        return ""
    # Remove script and style blocks entirely (tag + contents)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # <br> and block-closing tags become line breaks (li handled below)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(
        r"</(p|div|h[1-6]|tr|ul|ol|section|article|header|footer|blockquote|pre|dd|dt)\s*>",
        "\n", text, flags=re.IGNORECASE,
    )
    # List items start on a new line with a bullet
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities (covers &mdash;, &ndash;, &nbsp;, &amp;, numeric entities, etc.)
    text = html_mod.unescape(text)
    # Normalize spaces/tabs within each line, drop blank lines, preserve breaks
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# Markers that appear AFTER the JD content on job board pages.
# When found in the stripped text, everything from the marker onward is discarded.
_BOILERPLATE_MARKERS = [
    "Report this job",
    "Similar jobs",
    "People also viewed",
    "People who viewed",
    "Show more jobs like this",
    "Show fewer jobs like this",
    "More searches",
    "Explore top content",
    "Referrals increase your chances",
    "See who you know",
    "Get notified about new",
    "Sign in to create job alert",
    "Jobs you might like",
    "Recommended jobs",
    "More jobs like this",
]


def _extract_jd_from_html(html: str) -> str:
    """Extract job description text from an HTML page.

    Tries to find the JD content container first (LinkedIn, Greenhouse, Lever,
    Ashby, generic). Falls back to full-page strip with boilerplate truncation.
    """
    if not html:
        return ""

    # Try to extract content from known JD container elements.
    # These are common selectors used by job boards and ATSs.
    container_patterns = [
        # LinkedIn
        r'(?s)<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>\s*(?:<div[^>]*class="[^"]*(?:seniority|employment|job-function|industries))',
        r'(?s)<div[^>]*class="[^"]*jobs-description__content[^"]*"[^>]*>(.*?)</div>',
        r'(?s)<div[^>]*class="[^"]*jobs-box__html-content[^"]*"[^>]*>(.*?)</div>',
        # Greenhouse / Lever / Ashby (job boards)
        r'(?s)<div[^>]*id="content"[^>]*>(.*?)</div>\s*</div>',
        r'(?s)<section[^>]*class="[^"]*job-post[^"]*"[^>]*>(.*?)</section>',
        r'(?s)<div[^>]*class="[^"]*job-description[^"]*"[^>]*>(.*?)</div>',
        # Generic: <main> or <article>
        r'(?s)<main[^>]*>(.*?)</main>',
        r'(?s)<article[^>]*>(.*?)</article>',
    ]

    for pattern in container_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            extracted = _strip_html(match.group(1))
            if len(extracted) >= 200:
                return extracted

    # Fallback: strip full page, then truncate at boilerplate markers
    full_text = _strip_html(html)
    if not full_text:
        return ""

    # Find the earliest boilerplate marker and truncate
    earliest = len(full_text)
    for marker in _BOILERPLATE_MARKERS:
        idx = full_text.find(marker)
        if idx != -1 and idx < earliest:
            earliest = idx

    if earliest < len(full_text):
        full_text = full_text[:earliest].rstrip()

    return full_text


def _fetch_url(url: str, user_agent: str, timeout: int = 15) -> str:
    """Fetch a URL and return the response text.

    Tries httpx first. If blocked by Vercel JS challenge (403/429),
    falls back to a headless browser via Playwright if available.
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 429):
            from seeker_os.discovery.browser_fetch import fetch_with_browser, is_available
            if is_available():
                import logging
                logging.getLogger(__name__).warning(
                    "httpx blocked (%d), falling back to headless browser for %s",
                    e.response.status_code, url,
                )
                return fetch_with_browser(url)
        raise


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


def fetch_greenhouse_job(board: str, job_id: str, user_agent: str) -> dict:
    """Fetch full job data from Greenhouse API and return the raw JSON dict.

    This includes structured metadata (title, location, compensation, metadata)
    that can be used to populate JobCard fields for manual job entry.
    """
    import json
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    text = _fetch_url(url, user_agent)
    return json.loads(text)


def _fetch_ashby(board: str, user_agent: str) -> str:
    """Fetch JD from Ashby API (board-level, then find job)."""
    # Ashby's API is board-level; we'd need to find the specific job.
    # For Phase 1, fall back to apply_url HTML fetch.
    raise NotImplementedError("Ashby API fetch — falling back to apply_url")


def _fetch_lever(board: str, user_agent: str) -> str:
    """Fetch JD from Lever API."""
    # Lever's posting API is board-level
    raise NotImplementedError("Lever API fetch — falling back to apply_url")


def _fetch_hiring_cafe_detail(detail_url: str, user_agent: str) -> str:
    """Fetch JD from hiring.cafe job detail page.

    The detail page has __NEXT_DATA__ with job.job_information.description (HTML).
    Returns the raw HTML description (not stripped) for richer rendering.
    """
    import json
    import re

    html = _fetch_url(detail_url, user_agent)
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    if not match:
        # Fall back to stripping the whole page
        return _strip_html(html)

    data = json.loads(match.group(1))
    job = data.get("props", {}).get("pageProps", {}).get("job", {})
    desc = job.get("job_information", {}).get("description", "")
    if desc:
        return desc  # Return raw HTML — the frontend can render it
    # Fallback: strip the whole page
    return _strip_html(html)


def fetch_jd(
    job_id: int,
    ats_source: str | None,
    ats_board_token: str | None,
    ats_job_id: str | None,
    apply_url: str,
    user_agent: str = "Mozilla/5.0",
    delay: float = 2.0,
    detail_url: str | None = None,
) -> JDFetchResult:
    """Fetch full JD for a single job.

    Fetch order:
    1. ATS API (greenhouse) if available
    2. apply_url HTML (original ATS posting)
    3. hiring.cafe detail page (if detail_url is set) — most reliable fallback

    If fetch fails: return status='failed' with error message.
    """
    time.sleep(delay)  # human-like delay

    # Try ATS API first (greenhouse)
    if ats_source == "greenhouse" and ats_board_token and ats_job_id:
        try:
            jd_text = _fetch_greenhouse(ats_board_token, ats_job_id, user_agent)
            if jd_text and len(jd_text) >= 100:
                return JDFetchResult(
                    job_id=job_id, jd_text=jd_text, status="fetched",
                    source_used="greenhouse_api",
                )
        except Exception:
            pass  # Fall through to apply_url

    # Try apply_url (original ATS posting)
    try:
        html = _fetch_url(apply_url, user_agent)
        jd_text = _extract_jd_from_html(html)
        if jd_text and len(jd_text) >= 100:
            return JDFetchResult(
                job_id=job_id, jd_text=jd_text, status="fetched",
                source_used=f"apply_url ({ats_source or 'unknown'})",
            )
    except Exception:
        pass  # Fall through to hiring.cafe detail

    # Fallback: hiring.cafe detail page
    if detail_url:
        try:
            jd_html = _fetch_hiring_cafe_detail(detail_url, user_agent)
            if jd_html and len(jd_html) >= 100:
                return JDFetchResult(
                    job_id=job_id, jd_text=jd_html, status="fetched",
                    source_used="hiring_cafe_detail",
                )
        except Exception as e:
            return JDFetchResult(
                job_id=job_id, jd_text="", status="failed",
                source_used="hiring_cafe_detail", error=str(e),
            )

    # All methods failed
    return JDFetchResult(
        job_id=job_id, jd_text="", status="failed",
        source_used=ats_source or "apply_url",
        error="All fetch methods failed (ATS API, apply_url, hiring.cafe detail)",
    )
