"""Pytest configuration for Seeker OS backend tests.

Tests run against the live (non-demo) application by default so that mutation
endpoints and personal config loading are exercised. The demo-mode guard has its
own tests.
"""

import os

os.environ["DEMO_MODE"] = "false"
