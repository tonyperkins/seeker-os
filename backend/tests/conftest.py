"""Pytest configuration for Seeker OS backend tests."""

import os

# Disable Playwright browser fallback so tests don't launch real browser windows.
# The hiring.cafe adapter checks this env var before attempting a browser fetch.
os.environ["SEEKER_OS_NO_BROWSER"] = "1"
