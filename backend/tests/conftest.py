"""Pytest configuration for Seeker OS backend tests."""

import os

# Disable Playwright browser fallback so tests don't launch real browser windows.
# The hiring.cafe adapter checks this env var before attempting a browser fetch.
os.environ["SEEKER_OS_NO_BROWSER"] = "1"


import pytest


@pytest.fixture(autouse=True)
def _no_llm_metadata_extraction(monkeypatch):
    """Stub the LLM metadata extractor for ALL tests.

    POST /api/jobs calls extract_metadata_from_jd(), which routes a real LLM
    request through the model router — ~10s of network latency per created
    job, real token spend, and junk rows in the real llm_calls ledger. No
    test asserts on extracted metadata via the API path, so the stub returns
    the same empty ExtractedMetadata the extractor returns on failure.

    A test that needs the real extractor can undo this with
    monkeypatch.setattr back to the original (kept on the module as
    _real_extract_metadata_from_jd by this fixture).
    """
    from seeker_os.analysis import metadata_extractor as me

    if not hasattr(me, "_real_extract_metadata_from_jd"):
        me._real_extract_metadata_from_jd = me.extract_metadata_from_jd

    def _stub(*args, **kwargs):
        return me.ExtractedMetadata()

    monkeypatch.setattr(me, "extract_metadata_from_jd", _stub)
