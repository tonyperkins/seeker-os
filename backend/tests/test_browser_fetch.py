"""Tests for browser_fetch cookie caching and challenge handling.

These tests mock Playwright to verify the logic without requiring a real browser.
"""

from unittest.mock import MagicMock, patch

import pytest

from seeker_os.discovery import browser_fetch


class _FakeTimeout(Exception):
    """Stand-in for PlaywrightTimeout when playwright isn't installed."""


@pytest.fixture(autouse=True)
def _reset_cookie_cache():
    browser_fetch._cached_cookies.clear()
    browser_fetch._cookie_timestamps.clear()
    yield
    browser_fetch._cached_cookies.clear()
    browser_fetch._cookie_timestamps.clear()


def _make_mock_playwright(content_sequence, cookies=None, wait_for_function_raises=True):
    """Build a mock sync_playwright context that returns content in sequence.

    content_sequence: list of strings returned by page.content() in call order.
    cookies: list of cookie dicts returned by context.cookies().
    wait_for_function_raises: if True, wait_for_function always raises _FakeTimeout.
        if False, it succeeds (simulating challenge resolved).
    """
    mock_page = MagicMock()
    mock_page.content.side_effect = content_sequence
    mock_page.title.return_value = "Test Page"
    mock_page.reload = MagicMock()

    if wait_for_function_raises:
        mock_page.wait_for_function.side_effect = _FakeTimeout("timeout")
    else:
        mock_page.wait_for_function.return_value = None

    mock_context = MagicMock()
    mock_context.cookies.return_value = cookies or []

    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_page.context = mock_context

    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser

    mock_pw_cm = MagicMock()
    mock_pw_cm.__enter__ = MagicMock(return_value=mock_playwright)
    mock_pw_cm.__exit__ = MagicMock(return_value=False)

    return mock_pw_cm


class TestChallengeNotSolved:
    """When the Vercel challenge never resolves, cookies must not be cached."""

    def test_no_cookie_cache_on_unresolved_challenge(self):
        """Bug: cookies were cached unconditionally with 'challenge solved' log."""
        challenge_html = '<html><title>Just a moment...</title><script>window._cf_chl_opt = {};</script>challenge page</html>'
        mock_pw = _make_mock_playwright(
            content_sequence=[challenge_html, challenge_html, challenge_html],
            cookies=[{"name": "_vcrcs", "value": "fake", "domain": "hiringcafe.com"}],
        )

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", return_value=mock_pw, create=True), \
             patch("seeker_os.discovery.browser_fetch.PlaywrightTimeout", _FakeTimeout, create=True):
            html = browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

        assert "challenge page" in html
        assert "hiringcafe.com" not in browser_fetch._cached_cookies

    def test_cookie_cache_on_solved_challenge(self):
        """When challenge resolves, cookies should be cached."""
        challenge_html = '<html><title>Just a moment...</title>challenge</html>'
        real_html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{}}</script></html>'

        mock_page = MagicMock()
        mock_page.content.side_effect = [challenge_html, real_html]
        mock_page.title.return_value = "Jobs"
        mock_page.reload = MagicMock()
        mock_page.wait_for_function.return_value = None  # challenge resolves

        mock_context = MagicMock()
        mock_context.cookies.return_value = [
            {"name": "_vcrcs", "value": "valid_token", "domain": "hiringcafe.com"}
        ]

        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_page.context = mock_context

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__ = MagicMock(return_value=mock_playwright)
        mock_pw_cm.__exit__ = MagicMock(return_value=False)

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", return_value=mock_pw_cm, create=True), \
             patch("seeker_os.discovery.browser_fetch.PlaywrightTimeout", _FakeTimeout, create=True):
            html = browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

        assert "__NEXT_DATA__" in html
        assert "hiringcafe.com" in browser_fetch._cached_cookies
        assert browser_fetch._cached_cookies["hiringcafe.com"]["_vcrcs"] == "valid_token"

    def test_content_refreshed_after_second_timeout(self):
        """Bug: after second timeout, content was stale (from initial page load)."""
        challenge_html = '<html><title>Just a moment...</title>old challenge</html>'
        refreshed_html = '<html><title>Just a moment...</title>newer challenge</html>'

        mock_pw = _make_mock_playwright(
            content_sequence=[challenge_html, refreshed_html, refreshed_html],
            cookies=[],
        )

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", return_value=mock_pw, create=True), \
             patch("seeker_os.discovery.browser_fetch.PlaywrightTimeout", _FakeTimeout, create=True):
            html = browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

        assert "newer challenge" in html
        assert "old challenge" not in html
