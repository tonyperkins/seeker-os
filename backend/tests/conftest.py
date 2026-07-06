"""Pytest configuration for Seeker OS backend tests.

Tests run against the live (non-demo) application by default so that mutation
endpoints and personal config loading are exercised. The demo-mode guard has its
own tests.
"""

import os

os.environ["DEMO_MODE"] = "false"

# Disable Playwright browser fallback so tests don't launch real browser windows.
# The hiring.cafe adapter checks this env var before attempting a browser fetch.
os.environ["SEEKER_OS_NO_BROWSER"] = "1"
