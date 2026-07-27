"""Tests for browser_fetch cookie caching, challenge handling, and FlareSolverr.

These tests mock Playwright and httpx to verify the logic without requiring
a real browser or FlareSolverr service.
"""

from unittest.mock import MagicMock, patch

import pytest

from seeker_os.discovery import browser_fetch


class _FakeTimeout(Exception):
    """Stand-in for PlaywrightTimeout when playwright isn't installed."""


@pytest.fixture(autouse=True)
def _reset_state():
    browser_fetch._cached_cookies.clear()
    browser_fetch._cookie_timestamps.clear()
    browser_fetch._cached_user_agents.clear()
    browser_fetch._flaresolverr_session_id = None
    yield
    browser_fetch._cached_cookies.clear()
    browser_fetch._cookie_timestamps.clear()
    browser_fetch._cached_user_agents.clear()
    browser_fetch._flaresolverr_session_id = None


@pytest.fixture(autouse=True)
def _no_flaresolverr(monkeypatch):
    """Ensure FlareSolverr is not configured by default in tests."""
    monkeypatch.delenv("FLARESOLVERR_URL", raising=False)


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
            content_sequence=[challenge_html, challenge_html, challenge_html, challenge_html],
            cookies=[{"name": "_vcrcs", "value": "fake", "domain": "hiringcafe.com"}],
        )

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", False), \
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
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", False), \
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
            content_sequence=[challenge_html, refreshed_html, refreshed_html, refreshed_html],
            cookies=[],
        )

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", False), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", return_value=mock_pw, create=True), \
             patch("seeker_os.discovery.browser_fetch.PlaywrightTimeout", _FakeTimeout, create=True):
            html = browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

        assert "newer challenge" in html
        assert "old challenge" not in html


class TestFlareSolverr:
    """Tests for FlareSolverr integration (preferred path when configured)."""

    def test_flaresolverr_used_directly_when_configured(self, monkeypatch):
        """When FlareSolverr is configured, go directly to it without trying stealth."""
        monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr:8191")
        real_html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{}}</script></html>'

        mock_session_resp = MagicMock()
        mock_session_resp.json.return_value = {"status": "ok", "session": "test-session-123"}
        mock_session_resp.raise_for_status = MagicMock()

        mock_fs_resp = MagicMock()
        mock_fs_resp.json.return_value = {
            "status": "ok",
            "solution": {
                "response": real_html,
                "url": "https://hiringcafe.com/jobs/test",
                "status": 200,
                "cookies": [
                    {"name": "cf_clearance", "value": "valid_cf_token", "domain": ".hiringcafe.com"}
                ],
                "userAgent": "Mozilla/5.0 test",
            },
        }
        mock_fs_resp.raise_for_status = MagicMock()

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", True), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", create=True) as mock_pw, \
             patch("httpx.post", side_effect=[mock_session_resp, mock_fs_resp]) as mock_post:
            html = browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

        assert "__NEXT_DATA__" in html
        assert "hiringcafe.com" in browser_fetch._cached_cookies
        assert browser_fetch._cached_cookies["hiringcafe.com"]["cf_clearance"] == "valid_cf_token"
        # Playwright should never be called
        mock_pw.assert_not_called()
        # Two httpx calls: session create + request.get
        assert mock_post.call_count == 2

    def test_flaresolverr_session_reused_across_calls(self, monkeypatch):
        """Session should be created once and reused for subsequent requests."""
        monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr:8191")
        real_html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{}}</script></html>'

        mock_session_resp = MagicMock()
        mock_session_resp.json.return_value = {"status": "ok", "session": "test-session-456"}
        mock_session_resp.raise_for_status = MagicMock()

        mock_fs_resp = MagicMock()
        mock_fs_resp.json.return_value = {
            "status": "ok",
            "solution": {
                "response": real_html,
                "url": "https://hiringcafe.com/jobs/test",
                "status": 200,
                "cookies": [],
                "userAgent": "Mozilla/5.0 test",
            },
        }
        mock_fs_resp.raise_for_status = MagicMock()

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", True), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", create=True), \
             patch("httpx.post", side_effect=[mock_session_resp, mock_fs_resp, mock_fs_resp]) as mock_post:
            # First call: creates session + request.get
            browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")
            assert browser_fetch._flaresolverr_session_id == "test-session-456"
            assert mock_post.call_count == 2

            # Second call: reuses session, only request.get
            browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")
            assert mock_post.call_count == 3  # No new session create

            # Verify session ID was passed in the request payload
            second_call_args = mock_post.call_args_list[2]
            assert second_call_args.kwargs["json"]["session"] == "test-session-456"

    def test_flaresolverr_error_raises_runtime(self, monkeypatch):
        """When FlareSolverr returns an error, RuntimeError should be raised."""
        monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr:8191")

        mock_session_resp = MagicMock()
        mock_session_resp.json.return_value = {"status": "ok", "session": "test-session"}
        mock_session_resp.raise_for_status = MagicMock()

        mock_fs_resp = MagicMock()
        mock_fs_resp.json.return_value = {
            "status": "error",
            "message": "Could not solve challenge",
        }
        mock_fs_resp.raise_for_status = MagicMock()

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", False), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", create=True), \
             patch("httpx.post", side_effect=[mock_session_resp, mock_fs_resp]):
            with pytest.raises(RuntimeError, match="FlareSolverr returned error"):
                browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

    def test_flaresolverr_caches_user_agent(self, monkeypatch):
        """FlareSolverr should cache the user-agent alongside cookies."""
        monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr:8191")
        real_html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{}}</script></html>'
        fs_user_agent = "Mozilla/5.0 (X11; Linux x86_64) Chrome/148.0.0.0"

        mock_session_resp = MagicMock()
        mock_session_resp.json.return_value = {"status": "ok", "session": "test-session"}
        mock_session_resp.raise_for_status = MagicMock()

        mock_fs_resp = MagicMock()
        mock_fs_resp.json.return_value = {
            "status": "ok",
            "solution": {
                "response": real_html,
                "url": "https://hiringcafe.com/jobs/test",
                "status": 200,
                "cookies": [
                    {"name": "cf_clearance", "value": "valid_cf_token", "domain": ".hiringcafe.com"}
                ],
                "userAgent": fs_user_agent,
            },
        }
        mock_fs_resp.raise_for_status = MagicMock()

        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", True), \
             patch.object(browser_fetch, "_STEALTH_AVAILABLE", False), \
             patch("seeker_os.discovery.browser_fetch.sync_playwright", create=True), \
             patch("httpx.post", side_effect=[mock_session_resp, mock_fs_resp]):
            browser_fetch.fetch_with_browser("https://hiringcafe.com/jobs/test")

        assert browser_fetch.get_cached_user_agent("hiringcafe.com") == fs_user_agent

    def test_is_available_with_flaresolverr_only(self, monkeypatch):
        """is_available() returns True when FlareSolverr is configured but Playwright isn't."""
        monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr:8191")
        monkeypatch.delenv("SEEKER_OS_NO_BROWSER", raising=False)
        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", False):
            assert browser_fetch.is_available() is True

    def test_is_available_with_neither(self, monkeypatch):
        """is_available() returns False when neither Playwright nor FlareSolverr is available."""
        monkeypatch.delenv("FLARESOLVERR_URL", raising=False)
        monkeypatch.delenv("SEEKER_OS_NO_BROWSER", raising=False)
        with patch.object(browser_fetch, "_PLAYWRIGHT_AVAILABLE", False):
            assert browser_fetch.is_available() is False
