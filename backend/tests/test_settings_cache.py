"""Regression tests for the standard cached settings read path."""

from seeker_os.config import get_settings, invalidate_settings_cache


def test_repeated_settings_reads_reuse_cached_instance(tmp_path, monkeypatch):
    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", tmp_path)
    invalidate_settings_cache()
    try:
        first = get_settings()
        second = get_settings()
        assert second is first
    finally:
        invalidate_settings_cache()
