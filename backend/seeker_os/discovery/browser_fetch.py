"""Headless browser fallback for Vercel/Cloudflare JS challenges.

When hiringcafe.com (or other sites behind Vercel/Cloudflare bot protection)
returns a 403 with a JS challenge, httpx cannot solve it. This module uses
Playwright with stealth evasions to load the page in a real headless browser,
wait for the challenge to resolve, and return the final HTML.

If stealth evasions aren't enough (e.g. Cloudflare detects the browser in
Docker/Xvfb environments), the module falls back to FlareSolverr — a
purpose-built proxy service that solves Cloudflare challenges.

Cookie reuse optimization: after solving the challenge once, the verification
cookies (Vercel _vcrcs or Cloudflare cf_clearance) are cached and can be
injected into httpx requests, avoiding the need to launch a browser for
every subsequent page.

Playwright is an optional dependency: `pip install -e ".[browser]"` plus
`playwright install chromium`. If not installed, the fallback is unavailable
and the caller gets a clear error message.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

try:
    from playwright_stealth import Stealth
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

# Cached verification cookies from the last successful challenge solve.
# Keyed by domain. Expires after _COOKIE_TTL_SECONDS.
_cached_cookies: dict[str, dict[str, str]] = {}
_cookie_timestamps: dict[str, float] = {}
_COOKIE_TTL_SECONDS = 300  # 5 minutes — challenge cookies are short-lived

# Strings that indicate a JS challenge page (Vercel or Cloudflare).
_CHALLENGE_MARKERS = [
    "Vercel Security Checkpoint",
    "Just a moment",  # Cloudflare managed challenge
    "_cf_chl_opt",  # Cloudflare challenge JS variable
    "cf-mitigated: challenge",  # Cloudflare header (shouldn't be in body, but just in case)
]


def is_available() -> bool:
    """Return True if Playwright or FlareSolverr is available and not disabled."""
    if os.environ.get("SEEKER_OS_NO_BROWSER"):
        return False
    if _PLAYWRIGHT_AVAILABLE:
        return True
    if _get_flaresolverr_url():
        return True
    return False


def get_cached_cookies(domain: str) -> dict[str, str] | None:
    """Return cached verification cookies for a domain, or None if expired/missing."""
    cookies = _cached_cookies.get(domain)
    if cookies is None:
        return None
    ts = _cookie_timestamps.get(domain, 0)
    if time.time() - ts > _COOKIE_TTL_SECONDS:
        _cached_cookies.pop(domain, None)
        _cookie_timestamps.pop(domain, None)
        return None
    return cookies


def _is_challenge_page(content: str) -> bool:
    """Check if the page content is a Vercel or Cloudflare challenge page."""
    return any(marker in content for marker in _CHALLENGE_MARKERS)


def _get_flaresolverr_url() -> str | None:
    """Return FlareSolverr URL from env var, or None if not configured."""
    return os.environ.get("FLARESOLVERR_URL") or None


def _cache_cookies_from_list(url: str, cookies: list[dict]) -> None:
    """Cache cookies from a list of cookie dicts (FlareSolverr format)."""
    from urllib.parse import urlparse
    domain = urlparse(url).hostname or ""
    cookie_jar: dict[str, str] = {}
    for c in cookies:
        c_domain = c.get("domain", "")
        if c_domain == domain or c_domain == f".{domain}" or domain.endswith(c_domain.lstrip(".")):
            cookie_jar[c["name"]] = c["value"]
    if cookie_jar:
        _cached_cookies[domain] = cookie_jar
        _cookie_timestamps[domain] = time.time()
        logger.info("Cached %d cookies for %s", len(cookie_jar), domain)


def _fetch_with_flaresolverr(url: str, timeout_ms: int = 60000) -> str:
    """Fetch a URL via FlareSolverr proxy, which solves Cloudflare challenges.

    FlareSolverr runs as a separate Docker service and exposes an HTTP API
    on port 8191. It uses a real browser with anti-detection measures to
    solve Cloudflare managed challenges.
    """
    fs_url = _get_flaresolverr_url()
    if not fs_url:
        raise RuntimeError("FlareSolverr URL not configured (FLARESOLVERR_URL env var)")

    import httpx

    logger.info("Trying FlareSolverr fallback for %s", url)
    try:
        resp = httpx.post(
            fs_url.rstrip("/") + "/v1",
            json={
                "cmd": "request.get",
                "url": url,
                "maxTimeout": timeout_ms,
            },
            timeout=timeout_ms / 1000 + 30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"FlareSolverr request failed: {e}")

    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr returned error: {data.get('message', 'unknown')}")

    solution = data.get("solution", {})
    html = solution.get("response", "")
    if not html:
        raise RuntimeError("FlareSolverr returned empty response")

    logger.info(
        "FlareSolverr succeeded — url=%s, status=%s, content_len=%d, has_NEXT_DATA=%s",
        solution.get("url", ""), solution.get("status", ""),
        len(html), "__NEXT_DATA__" in html,
    )

    if "__NEXT_DATA__" in html:
        cookies = solution.get("cookies", [])
        if cookies:
            _cache_cookies_from_list(url, cookies)
        user_agent = solution.get("userAgent", "")
        if user_agent:
            logger.info("FlareSolverr user-agent: %s", user_agent[:80])

    return html


def _solve_challenge_and_cache_cookies(url: str, timeout_ms: int = 60000) -> str:
    """Launch browser with stealth evasions, solve JS challenge, cache cookies, return HTML.

    Uses playwright-stealth to patch browser fingerprints (WebGL, canvas, etc.)
    to avoid detection by Cloudflare. If stealth isn't enough and the challenge
    remains unresolved, falls back to FlareSolverr if configured.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        fs_url = _get_flaresolverr_url()
        if fs_url:
            logger.info("Playwright not installed, using FlareSolverr directly")
            return _fetch_with_flaresolverr(url, timeout_ms=timeout_ms)
        raise RuntimeError(
            "Playwright is not installed. Install with: "
            'pip install -e ".[browser]" && playwright install chromium'
        )

    from urllib.parse import urlparse

    if _STEALTH_AVAILABLE:
        logger.info("Using playwright-stealth evasions")
        pw_ctx = Stealth().use_sync(sync_playwright())
    else:
        logger.warning("playwright-stealth not installed, using plain Playwright")
        pw_ctx = sync_playwright()

    with pw_ctx as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            page = browser.new_page()
            if not _STEALTH_AVAILABLE:
                page.add_init_script(
                    'Object.defineProperty(navigator, "webdriver", { get: () => undefined });'
                )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            content = page.content()
            logger.info(
                "Initial page loaded — url=%s, title=%s, content_len=%d, "
                "has_NEXT_DATA=%s, is_challenge=%s",
                page.url, page.title(), len(content),
                "__NEXT_DATA__" in content, _is_challenge_page(content),
            )
            logger.debug("Initial page content (first 500 chars): %s", content[:500])

            if _is_challenge_page(content):
                logger.info("JS challenge detected (Vercel/Cloudflare), waiting for JS to resolve...")
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except PlaywrightTimeout:
                    logger.warning("networkidle timeout during challenge, continuing to poll...")

                content = page.content()
                logger.info(
                    "After networkidle — url=%s, title=%s, content_len=%d, has_NEXT_DATA=%s",
                    page.url, page.title(), len(content), "__NEXT_DATA__" in content,
                )
                logger.debug("Post-networkidle content (first 500 chars): %s", content[:500])

                if "__NEXT_DATA__" not in content:
                    try:
                        page.wait_for_function(
                            """() => {
                                return document.querySelector('script#__NEXT_DATA__') !== null;
                            }""",
                            timeout=timeout_ms,
                        )
                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                        except PlaywrightTimeout:
                            pass
                        content = page.content()
                        logger.info(
                            "Challenge resolved — url=%s, title=%s, content_len=%d",
                            page.url, page.title(), len(content),
                        )
                    except PlaywrightTimeout:
                        logger.warning(
                            "Challenge timeout — url=%s, title=%s, content_len=%d, "
                            "has_NEXT_DATA=%s, content_snippet=%s",
                            page.url, page.title(), len(content),
                            "__NEXT_DATA__" in content, content[:300],
                        )
                        logger.warning("Challenge timeout, trying reload...")
                        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                        try:
                            page.wait_for_load_state("networkidle", timeout=timeout_ms)
                        except PlaywrightTimeout:
                            pass
                        content = page.content()
                        logger.info(
                            "After reload — url=%s, title=%s, content_len=%d, has_NEXT_DATA=%s",
                            page.url, page.title(), len(content), "__NEXT_DATA__" in content,
                        )
                        try:
                            page.wait_for_function(
                                """() => {
                                    return document.querySelector('script#__NEXT_DATA__') !== null;
                                }""",
                                timeout=timeout_ms,
                            )
                            content = page.content()
                        except PlaywrightTimeout:
                            logger.warning(
                                "Challenge still unresolved after reload — url=%s, title=%s, "
                                "content_len=%d, has_NEXT_DATA=%s, content_snippet=%s",
                                page.url, page.title(), len(content),
                                "__NEXT_DATA__" in content, content[:300],
                            )
                            content = page.content()

            challenge_solved = "__NEXT_DATA__" in content
            if challenge_solved:
                context = page.context
                all_cookies = context.cookies()
                domain = urlparse(url).hostname or ""
                cookie_jar: dict[str, str] = {}
                for c in all_cookies:
                    c_domain = c.get("domain", "")
                    if c_domain == domain or c_domain == f".{domain}" or domain.endswith(c_domain.lstrip(".")):
                        cookie_jar[c["name"]] = c["value"]
                if cookie_jar:
                    _cached_cookies[domain] = cookie_jar
                    _cookie_timestamps[domain] = time.time()
                    logger.info("Cached %d cookies for %s (challenge solved)", len(cookie_jar), domain)
            else:
                logger.warning(
                    "Not caching cookies — page does not contain __NEXT_DATA__ (challenge unresolved). "
                    "Final url=%s, title=%s, content_len=%d, content_snippet=%s",
                    page.url, page.title(), len(content), content[:300],
                )

            return content
        finally:
            browser.close()


def fetch_with_browser(url: str, timeout_ms: int = 60000) -> str:
    """Fetch a URL using a headless browser with stealth evasions, solving any JS challenge.

    Tries Playwright with playwright-stealth first. If the challenge remains
    unresolved (no __NEXT_DATA__ in final content), falls back to FlareSolverr
    if configured via FLARESOLVERR_URL env var.

    Raises RuntimeError if neither Playwright nor FlareSolverr is available.
    Raises TimeoutError if the page doesn't load within timeout_ms.
    """
    content = _solve_challenge_and_cache_cookies(url, timeout_ms=timeout_ms)

    if "__NEXT_DATA__" not in content:
        fs_url = _get_flaresolverr_url()
        if fs_url:
            logger.warning("Stealth browser failed to resolve challenge, falling back to FlareSolverr")
            content = _fetch_with_flaresolverr(url, timeout_ms=timeout_ms)
        else:
            logger.warning(
                "Challenge unresolved and FlareSolverr not configured (FLARESOLVERR_URL env var). "
                "Consider adding FlareSolverr to docker-compose for Cloudflare challenges."
            )

    return content
