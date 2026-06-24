"""Tests for the models/providers API endpoints.

Covers:
- GET /api/models — provider configuration (providers, tiers, tasks)
- PUT /api/models/providers/{id} — update a provider (enable/disable, label, etc.)
- PUT /api/models/tiers/{tier} — update a tier mapping
- PUT /api/models/tasks/{task} — update a task override
- POST /api/models/test/{provider_id} — test provider connectivity
- POST /api/models/fetch/{provider_id} — fetch models from a provider

OAuth endpoints (POST /api/models/anthropic/oauth/*) are skipped — they require
external browser redirects and network calls to Anthropic.

The provider "test" and "fetch" endpoints may succeed or fail depending on
whether a real backend (e.g. Ollama) is running locally and whether API keys
are set. These tests accept either a success (200) or an error (4xx/5xx) and
only assert the response shape / error-handling contract.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
import seeker_os.config as config


# Provider/tier/task identifiers from providers.example.yml
PROVIDER_ANTHROPIC = "anthropic_direct"
PROVIDER_KILO = "kilo"
PROVIDER_OLLAMA = "ollama_local"
TIER_HEAVY = "heavy"
TIER_MODERATE = "moderate"
TASK_RESUME_GEN_HIGH = "resume_generation_high_value"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a TestClient with a temp config dir (providers.yml from example).

    Patches seeker_os.config.CONFIG_DIR and PROJECT_ROOT so config reads/writes
    and .env writes are isolated to tmp_path.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Copy the example providers config as the real providers.yml
    example = config.PROJECT_ROOT / "config" / "providers.example.yml"
    shutil.copy(example, config_dir / "providers.yml")

    # Redirect config + project root to the temp dir
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Provider config — GET /api/models
# ---------------------------------------------------------------------------

class TestGetProvidersConfig:
    def test_returns_providers_tiers_tasks(self, client):
        r = client.get("/api/models")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        assert "tiers" in data
        assert "tasks" in data

    def test_providers_list_has_expected_ids(self, client):
        r = client.get("/api/models")
        data = r.json()
        ids = {p["id"] for p in data["providers"]}
        assert PROVIDER_ANTHROPIC in ids
        assert PROVIDER_KILO in ids
        assert PROVIDER_OLLAMA in ids

    def test_provider_info_shape(self, client):
        r = client.get("/api/models")
        data = r.json()
        provider = next(p for p in data["providers"] if p["id"] == PROVIDER_OLLAMA)
        # Required fields per ProviderInfoResponse
        for field in ("id", "type", "label", "enabled", "api_key_set", "models"):
            assert field in provider
        assert provider["type"] == "openai_compatible"
        assert isinstance(provider["models"], list)

    def test_tiers_structure(self, client):
        r = client.get("/api/models")
        tiers = r.json()["tiers"]
        assert TIER_HEAVY in tiers
        assert "provider" in tiers[TIER_HEAVY]
        assert "model" in tiers[TIER_HEAVY]

    def test_tasks_structure(self, client):
        r = client.get("/api/models")
        tasks = r.json()["tasks"]
        assert TASK_RESUME_GEN_HIGH in tasks
        assert "tier" in tasks[TASK_RESUME_GEN_HIGH]

    def test_api_key_not_leaked(self, client):
        """The raw api_key value must never be sent to the client."""
        r = client.get("/api/models")
        for p in r.json()["providers"]:
            assert "api_key" not in p
            assert "api_key_set" in p

    def test_providers_disabled_by_default(self, client):
        """The example config ships all providers disabled."""
        r = client.get("/api/models")
        for p in r.json()["providers"]:
            assert p["enabled"] is False


# ---------------------------------------------------------------------------
# Provider config — PUT /api/models/providers/{id}
# ---------------------------------------------------------------------------

class TestUpdateProvider:
    def test_enable_provider(self, client):
        r = client.put(
            f"/api/models/providers/{PROVIDER_OLLAMA}",
            json={"enabled": True},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == PROVIDER_OLLAMA
        assert data["enabled"] is True

    def test_disable_provider(self, client):
        # First enable, then disable
        client.put(f"/api/models/providers/{PROVIDER_OLLAMA}", json={"enabled": True})
        r = client.put(
            f"/api/models/providers/{PROVIDER_OLLAMA}",
            json={"enabled": False},
        )
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_update_label(self, client):
        r = client.put(
            f"/api/models/providers/{PROVIDER_OLLAMA}",
            json={"label": "My Ollama"},
        )
        assert r.status_code == 200
        assert r.json()["label"] == "My Ollama"

    def test_update_persists_to_config(self, client):
        """A PUT should persist the change so a subsequent GET reflects it."""
        client.put(f"/api/models/providers/{PROVIDER_KILO}", json={"enabled": True})
        r = client.get("/api/models")
        kilo = next(p for p in r.json()["providers"] if p["id"] == PROVIDER_KILO)
        assert kilo["enabled"] is True

    def test_update_provider_not_found(self, client):
        r = client.put(
            "/api/models/providers/nonexistent_provider",
            json={"enabled": True},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tier management — PUT /api/models/tiers/{tier}
# ---------------------------------------------------------------------------

class TestUpdateTier:
    def test_update_tier_mapping(self, client):
        r = client.put(
            f"/api/models/tiers/{TIER_HEAVY}",
            json={"provider": PROVIDER_OLLAMA, "model": "some-model"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == PROVIDER_OLLAMA
        assert data["model"] == "some-model"

    def test_update_tier_persists(self, client):
        client.put(
            f"/api/models/tiers/{TIER_MODERATE}",
            json={"provider": PROVIDER_KILO, "model": "kilo-model"},
        )
        r = client.get("/api/models")
        tier = r.json()["tiers"][TIER_MODERATE]
        assert tier["provider"] == PROVIDER_KILO
        assert tier["model"] == "kilo-model"

    def test_update_new_tier(self, client):
        """Updating a tier that doesn't yet exist should create it."""
        r = client.put(
            "/api/models/tiers/custom_tier",
            json={"provider": PROVIDER_OLLAMA, "model": "m1"},
        )
        assert r.status_code == 200
        r2 = client.get("/api/models")
        assert "custom_tier" in r2.json()["tiers"]


# ---------------------------------------------------------------------------
# Task overrides — PUT /api/models/tasks/{task}
# ---------------------------------------------------------------------------

class TestUpdateTask:
    def test_update_task_tier(self, client):
        r = client.put(
            f"/api/models/tasks/{TASK_RESUME_GEN_HIGH}",
            json={"tier": TIER_MODERATE},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == TIER_MODERATE

    def test_update_task_with_provider_model(self, client):
        r = client.put(
            f"/api/models/tasks/{TASK_RESUME_GEN_HIGH}",
            json={"tier": TIER_HEAVY, "provider": PROVIDER_OLLAMA, "model": "m1"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == PROVIDER_OLLAMA
        assert data["model"] == "m1"

    def test_update_task_persists(self, client):
        client.put(
            f"/api/models/tasks/{TASK_RESUME_GEN_HIGH}",
            json={"tier": "light"},
        )
        r = client.get("/api/models")
        task = r.json()["tasks"][TASK_RESUME_GEN_HIGH]
        assert task["tier"] == "light"

    def test_update_new_task(self, client):
        r = client.put(
            "/api/models/tasks/custom_task",
            json={"tier": TIER_MODERATE},
        )
        assert r.status_code == 200
        r2 = client.get("/api/models")
        assert "custom_task" in r2.json()["tasks"]


# ---------------------------------------------------------------------------
# Provider actions — POST /api/models/test/{provider_id}
# ---------------------------------------------------------------------------

class TestProviderConnectivity:
    def test_test_provider_not_found(self, client):
        r = client.post("/api/models/test/nonexistent_provider")
        assert r.status_code == 404

    def test_test_provider_disabled_returns_404(self, client):
        """A disabled provider is not 'available', so testing it 404s."""
        r = client.post(f"/api/models/test/{PROVIDER_OLLAMA}")
        assert r.status_code == 404

    def test_test_provider_enabled_returns_health(self, client):
        """Enable ollama_local then test — 200 with a health payload.

        healthy may be True (Ollama running locally) or False (not running);
        both are valid. We only assert the response shape.
        """
        client.put(f"/api/models/providers/{PROVIDER_OLLAMA}", json={"enabled": True})
        r = client.post(f"/api/models/test/{PROVIDER_OLLAMA}")
        assert r.status_code == 200
        data = r.json()
        assert "provider_id" in data
        assert "healthy" in data
        assert "message" in data

    def test_test_all_providers(self, client):
        """POST /api/models/test-all returns a list (possibly empty)."""
        r = client.post("/api/models/test-all")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Provider actions — POST /api/models/fetch/{provider_id}
# ---------------------------------------------------------------------------

class TestFetchModels:
    def test_fetch_models_not_found(self, client):
        r = client.post("/api/models/fetch/nonexistent_provider")
        assert r.status_code == 404

    def test_fetch_models_disabled_returns_404(self, client):
        r = client.post(f"/api/models/fetch/{PROVIDER_OLLAMA}")
        assert r.status_code == 404

    def test_fetch_models_enabled(self, client):
        """Enable ollama_local then fetch — 200 (Ollama running) or 502 (not).

        Both are valid since no real backend is guaranteed in the test env.
        """
        client.put(f"/api/models/providers/{PROVIDER_OLLAMA}", json={"enabled": True})
        r = client.post(f"/api/models/fetch/{PROVIDER_OLLAMA}")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            assert isinstance(r.json(), list)
