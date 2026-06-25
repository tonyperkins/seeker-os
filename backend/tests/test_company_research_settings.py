"""Tests for company research settings API — secret handling and config write-back."""

from __future__ import annotations

import os
import shutil
import yaml
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def cr_settings_client(tmp_path, monkeypatch):
    """Create a test client with isolated config and .env paths."""
    from seeker_os.config import CONFIG_DIR, PROJECT_ROOT

    test_config = tmp_path / "config"
    test_config.mkdir()
    for f in CONFIG_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, test_config / f.name)

    # Remove any existing company_research.yml so we test creation
    cr_yml = test_config / "company_research.yml"
    if cr_yml.exists():
        cr_yml.unlink()

    test_env = tmp_path / ".env"

    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
    monkeypatch.setattr("seeker_os.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("seeker_os.config_writer.CONFIG_DIR", test_config)
    monkeypatch.setattr("seeker_os.api.company_research_settings.CONFIG_DIR", test_config)

    from seeker_os.api.app import app
    client = TestClient(app)

    # Clean up any stale RETRIEVAL_API_KEY from previous tests
    old_val = os.environ.pop("RETRIEVAL_API_KEY", None)

    yield client, test_config, test_env

    # Restore env var after test
    if old_val is not None:
        os.environ["RETRIEVAL_API_KEY"] = old_val
    else:
        os.environ.pop("RETRIEVAL_API_KEY", None)


class TestRetrievalSettingsGet:
    def test_get_returns_defaults_when_no_config(self, cr_settings_client):
        """GET should return defaults when company_research.yml doesn't exist."""
        client, test_config, _ = cr_settings_client
        resp = client.get("/api/settings/company-research")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_type"] == ""
        assert data["api_key_configured"] is False
        assert data["max_results"] == 5
        assert data["confidence_floor"] == 0.3

    def test_get_never_returns_api_key(self, cr_settings_client):
        """GET response must never contain the API key value."""
        client, test_config, test_env = cr_settings_client

        # Save a key via PUT
        client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily", "api_key": "test-secret-key-123"},
        )

        resp = client.get("/api/settings/company-research")
        data = resp.json()
        assert data["api_key_configured"] is True
        # Key must not appear anywhere in the response
        assert "test-secret-key-123" not in resp.text


class TestRetrievalSettingsSave:
    def test_save_writes_env_reference_not_literal(self, cr_settings_client):
        """PUT must write ${RETRIEVAL_API_KEY} to company_research.yml, NOT the literal key."""
        client, test_config, test_env = cr_settings_client

        resp = client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily", "api_key": "test-secret-key-123"},
        )
        assert resp.status_code == 200

        # Check company_research.yml
        cr_path = test_config / "company_research.yml"
        assert cr_path.exists(), "company_research.yml should be created on first save"
        cr_data = yaml.safe_load(cr_path.read_text())
        retrieval = cr_data.get("retrieval", {})
        assert retrieval["api_key"] == "${RETRIEVAL_API_KEY}"
        assert "test-secret-key-123" not in cr_path.read_text()

    def test_save_writes_literal_to_env(self, cr_settings_client):
        """PUT must write the literal key to .env under RETRIEVAL_API_KEY."""
        client, test_config, test_env = cr_settings_client

        client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily", "api_key": "test-secret-key-456"},
        )

        assert test_env.exists(), ".env should be created"
        env_content = test_env.read_text()
        assert "RETRIEVAL_API_KEY=test-secret-key-456" in env_content

    def test_save_updates_os_environ(self, cr_settings_client):
        """PUT must call os.environ.update so the key takes effect without restart."""
        client, test_config, test_env = cr_settings_client

        client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily", "api_key": "test-secret-key-789"},
        )
        assert os.environ.get("RETRIEVAL_API_KEY") == "test-secret-key-789"

    def test_first_save_creates_company_research_yml(self, cr_settings_client):
        """First save must create company_research.yml when it doesn't exist."""
        client, test_config, _ = cr_settings_client

        cr_path = test_config / "company_research.yml"
        assert not cr_path.exists()

        client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily", "api_key": "test-key-create"},
        )

        assert cr_path.exists()
        data = yaml.safe_load(cr_path.read_text())
        assert data["retrieval"]["type"] == "tavily"

    def test_get_returns_configured_true_after_save(self, cr_settings_client):
        """After saving a key, GET should return api_key_configured=true."""
        client, _, _ = cr_settings_client

        client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily", "api_key": "test-key-configured"},
        )

        resp = client.get("/api/settings/company-research")
        data = resp.json()
        assert data["api_key_configured"] is True
        assert data["provider_type"] == "tavily"

    def test_save_updates_other_fields(self, cr_settings_client):
        """PUT should update non-key fields in company_research.yml."""
        client, test_config, _ = cr_settings_client

        client.put(
            "/api/settings/company-research",
            json={
                "provider_type": "tavily",
                "api_key": "test-key-fields",
                "max_results": 10,
                "confidence_floor": 0.5,
                "staleness_months": 24,
            },
        )

        cr_path = test_config / "company_research.yml"
        data = yaml.safe_load(cr_path.read_text())
        assert data["retrieval"]["max_results"] == 10
        assert data["confidence_floor"] == 0.5
        assert data["staleness_months"] == 24


class TestTestConnection:
    def test_test_connection_no_provider(self, cr_settings_client):
        """Test connection should return ok=false when no provider configured."""
        client, _, _ = cr_settings_client
        resp = client.post("/api/settings/company-research/test-connection")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "No retrieval provider" in data["message"]

    def test_test_connection_no_key(self, cr_settings_client):
        """Test connection should return ok=false when provider set but no key."""
        client, _, _ = cr_settings_client
        client.put(
            "/api/settings/company-research",
            json={"provider_type": "tavily"},
        )
        resp = client.post("/api/settings/company-research/test-connection")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
