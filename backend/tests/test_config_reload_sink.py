"""Config-reload sink re-init test.

Tests that POST /api/settings/reload re-initializes the Langfuse sink
through the actual endpoint, handling both enabled→disabled and
disabled→enabled transitions.
"""

import types

import pytest
from fastapi.testclient import TestClient

import seeker_os.database as dbmod
from seeker_os.api.app import app
from seeker_os.database import get_connection, run_migrations
from seeker_os.observability import langfuse_sink as sink_mod

pytest.importorskip("langfuse")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


def _make_langfuse_settings(enabled: bool, keys: bool = True):
    """Build a Settings-like object with the given Langfuse config."""
    return types.SimpleNamespace(
        observability=types.SimpleNamespace(
            langfuse=types.SimpleNamespace(
                enabled=enabled,
                base_url="http://127.0.0.1:9",
                public_key="pk-lf-test" if keys else "",
                secret_key="sk-lf-test" if keys else "",
                capture_content=False,
                flush_interval_seconds=60.0,
            ),
        ),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with temp DB and patched config."""
    db_path = tmp_path / "reload_test.db"
    run_migrations(db_path)

    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)

    def _temp_get_connection(_db_path=None):
        return get_connection(db_path)

    monkeypatch.setattr(dbmod, "get_connection", _temp_get_connection)

    # Patch _sync_queries_from_yaml to no-op (we don't want YAML loading in tests)
    import seeker_os.api.app as app_mod
    monkeypatch.setattr(app_mod, "_sync_queries_from_yaml", lambda: None)

    # Patch get_settings to return disabled config by default
    import seeker_os.config as config_mod
    test_settings = _make_langfuse_settings(enabled=False)
    monkeypatch.setattr(config_mod, "get_settings", lambda config_dir=None: test_settings)

    # Also patch the get_settings used in settings_routes reload
    import seeker_os.api.settings_routes as settings_mod
    # The reload endpoint imports get_settings inside the function,
    # so we need to patch it in the config module namespace
    # (settings_routes does `from seeker_os.config import get_settings`)

    # Route OTel spans to in-memory exporter
    import langfuse as _lf
    real = _lf.Langfuse
    exp = InMemorySpanExporter()

    def patched(*args, **kwargs):
        kwargs.setdefault("span_exporter", exp)
        kwargs.setdefault("timeout", 1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_lf, "Langfuse", patched)

    # Ensure clean sink state
    sink_mod.disable_sink()

    yield TestClient(app)

    # Cleanup
    sink_mod.disable_sink()


class TestConfigReloadSinkReInit:
    def test_reload_disabled_to_enabled(self, client, monkeypatch):
        """Reloading config with Langfuse enabled initializes the sink."""
        # Start disabled
        assert sink_mod.get_sink() is None

        # Change config to enabled
        enabled_settings = _make_langfuse_settings(enabled=True)
        import seeker_os.config as config_mod
        monkeypatch.setattr(config_mod, "get_settings", lambda config_dir=None: enabled_settings)

        r = client.post("/api/settings/reload")
        assert r.status_code == 200
        assert "reloaded" in r.json()["message"].lower()

        assert sink_mod.get_sink() is not None, "sink not initialized after reload"

    def test_reload_enabled_to_disabled(self, client, monkeypatch):
        """Reloading config with Langfuse disabled shuts down the sink."""
        # Start enabled
        enabled_settings = _make_langfuse_settings(enabled=True)
        import seeker_os.config as config_mod
        monkeypatch.setattr(config_mod, "get_settings", lambda config_dir=None: enabled_settings)
        sink_mod.init_sink(enabled_settings)
        assert sink_mod.get_sink() is not None

        # Change config to disabled
        disabled_settings = _make_langfuse_settings(enabled=False)
        monkeypatch.setattr(config_mod, "get_settings", lambda config_dir=None: disabled_settings)

        r = client.post("/api/settings/reload")
        assert r.status_code == 200

        assert sink_mod.get_sink() is None, "sink not disabled after reload"

    def test_reload_enabled_no_keys_stays_disabled(self, client, monkeypatch):
        """Reloading with enabled=True but no keys leaves sink as None."""
        no_keys_settings = _make_langfuse_settings(enabled=True, keys=False)
        import seeker_os.config as config_mod
        monkeypatch.setattr(config_mod, "get_settings", lambda config_dir=None: no_keys_settings)

        r = client.post("/api/settings/reload")
        assert r.status_code == 200

        assert sink_mod.get_sink() is None, (
            "sink should be None when enabled but no keys configured"
        )

    def test_reload_idempotent_when_disabled(self, client):
        """Reloading multiple times when disabled is safe."""
        for _ in range(3):
            r = client.post("/api/settings/reload")
            assert r.status_code == 200
        assert sink_mod.get_sink() is None
