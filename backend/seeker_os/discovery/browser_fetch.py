"""Headless browser fallback for Vercel JS challenges.

When hiring.cafe (or other sites behind Vercel/Cloudflare bot protection)
returns a 403 with a JS challenge, httpx cannot solve it. This module uses
Playwright to load the page in a real headless browser, wait for the
challenge to resolve, and return the final HTML.

Playwright is an optional dependency: `pip install -e ".[browser]"` plus
`playwright install chromium`. If not installed, the fallback is unavailable
and the caller gets a clear error message.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


def is_available() -> bool:
    """Return True if Playwright is installed and browser fallback is not disabled."""
    if not _PLAYWRIGHT_AVAILABLE:
        return False
    import os
    if os.environ.get("SEEKER_OS_NO_BROWSER"):
        return False
    return True


def fetch_with_browser(url: str, timeout_ms: int = 30000) -> str:
    """Fetch a URL using a headless browser, solving any JS challenge.

    Launches Chromium in non-headless mode (Vercel's challenge detects
    headless mode and refuses to resolve). In server/Docker environments,
    Xvfb provides a virtual display — the Dockerfile installs it and
    the entrypoint wraps the process with xvfb-run.

    Raises RuntimeError if Playwright is not installed.
    Raises TimeoutError if the page doesn't load within timeout_ms.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright is not installed. Install with: "
            'pip install -e ".[browser]" && playwright install chromium'
        )

    with sync_playwright() as p:
        # headless=False is required — Vercel's challenge JS detects
        # headless mode and blocks. Use --no-sandbox for Docker compat.
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            page = browser.new_page()
            # Remove automation fingerprints
            page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", { get: () => undefined });'
            )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            content = page.content()

            # Vercel challenge detection — wait for JS to resolve.
            if "Vercel Security Checkpoint" in content:
                logger.info("Vercel challenge detected, waiting for JS to resolve...")
                try:
                    page.wait_for_function(
                        """() => {
                            return !document.title.includes('Vercel Security Checkpoint')
                                && document.querySelector('script#__NEXT_DATA__') !== null;
                        }""",
                        timeout=timeout_ms,
                    )
                    content = page.content()
                    logger.info("Vercel challenge resolved, page loaded: %s", page.title())
                except PlaywrightTimeout:
                    logger.warning("Vercel challenge timeout, trying reload...")
                    page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        page.wait_for_function(
                            """() => {
                                return !document.title.includes('Vercel Security Checkpoint')
                                    && document.querySelector('script#__NEXT_DATA__') !== null;
                            }""",
                            timeout=timeout_ms,
                        )
                        content = page.content()
                    except PlaywrightTimeout:
                        pass

            return content
        finally:
            browser.close()
