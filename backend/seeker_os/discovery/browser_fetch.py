"""Headless browser fallback for Vercel/Cloudflare JS challenges.

When hiringcafe.com (or other sites behind Vercel/Cloudflare bot protection)
returns a 403 with a JS challenge, httpx cannot solve it. This module uses
Playwright to load the page in a real headless browser, wait for the
challenge to resolve, and return the final HTML.

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
import time

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

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
    """Return True if Playwright is installed and browser fallback is not disabled."""
    if not _PLAYWRIGHT_AVAILABLE:
        return False
    import os
    if os.environ.get("SEEKER_OS_NO_BROWSER"):
        return False
    return True


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


def _solve_challenge_and_cache_cookies(url: str, timeout_ms: int = 30000) -> str:
    """Launch browser, solve JS challenge (Vercel or Cloudflare), cache cookies, return HTML.

    This is the full browser path — used when we don't have cached cookies.
    After solving the challenge, extracts all cookies for the URL's domain
    so they can be reused with httpx for subsequent requests.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright is not installed. Install with: "
            'pip install -e ".[browser]" && playwright install chromium'
        )

    from urllib.parse import urlparse

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            page = browser.new_page()
            page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", { get: () => undefined });'
            )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            content = page.content()

            if _is_challenge_page(content):
                logger.info("JS challenge detected (Vercel/Cloudflare), waiting for JS to resolve...")
                try:
                    page.wait_for_function(
                        """() => {
                            return document.querySelector('script#__NEXT_DATA__') !== null;
                        }""",
                        timeout=timeout_ms,
                    )
                    content = page.content()
                    logger.info("Challenge resolved, page loaded: %s", page.title())
                except PlaywrightTimeout:
                    logger.warning("Challenge timeout, trying reload...")
                    page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        page.wait_for_function(
                            """() => {
                                return document.querySelector('script#__NEXT_DATA__') !== null;
                            }""",
                            timeout=timeout_ms,
                        )
                        content = page.content()
                    except PlaywrightTimeout:
                        logger.warning("Challenge still unresolved after reload, using best-effort content")
                        content = page.content()

            # Only cache cookies if the page actually loaded (has __NEXT_DATA__).
            # Caching cookies from an unresolved challenge page poisons subsequent
            # httpx requests with invalid verification cookies.
            challenge_solved = "__NEXT_DATA__" in content
            if challenge_solved:
                context = page.context
                all_cookies = context.cookies()
                domain = urlparse(url).hostname or ""
                cookie_jar: dict[str, str] = {}
                for c in all_cookies:
                    # Match cookies for this domain (including dot-prefixed)
                    c_domain = c.get("domain", "")
                    if c_domain == domain or c_domain == f".{domain}" or domain.endswith(c_domain.lstrip(".")):
                        cookie_jar[c["name"]] = c["value"]
                if cookie_jar:
                    _cached_cookies[domain] = cookie_jar
                    _cookie_timestamps[domain] = time.time()
                    logger.info("Cached %d cookies for %s (challenge solved)", len(cookie_jar), domain)
            else:
                logger.warning("Not caching cookies — page does not contain __NEXT_DATA__ (challenge unresolved)")

            return content
        finally:
            browser.close()


def fetch_with_browser(url: str, timeout_ms: int = 30000) -> str:
    """Fetch a URL using a headless browser, solving any JS challenge.

    Launches Chromium in non-headless mode (Vercel/Cloudflare challenges detect
    headless mode and refuse to resolve). In server/Docker environments,
    Xvfb provides a virtual display — the Dockerfile installs it and
    the entrypoint wraps the process with xvfb-run.

    Raises RuntimeError if Playwright is not installed.
    Raises TimeoutError if the page doesn't load within timeout_ms.
    """
    return _solve_challenge_and_cache_cookies(url, timeout_ms=timeout_ms)
