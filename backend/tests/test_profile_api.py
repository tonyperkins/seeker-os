"""Tests for profile, filters, and accuracy-rules API endpoints."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import run_migrations
import seeker_os.config as config_mod
import seeker_os.api.profile_routes as profile_routes_mod
import seeker_os.config_writer as config_writer_mod

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """Point CONFIG_DIR at a temp dir populated with example config files.

    Patches CONFIG_DIR everywhere it was imported so route handlers and
    config writers all resolve to the temp directory.
    """
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()

    # Copy example configs (strip .example suffix) so Settings() can load them.
    # Example files are named e.g. "profile.example.yml" → copied to "profile.yml".
    for name in ("profile.yml", "filters.yml", "accuracy_rules.yml"):
        stem = name.rsplit(".", 1)[0]  # "profile.yml" -> "profile"
        src = EXAMPLE_CONFIG_DIR / f"{stem}.example.yml"
        if src.exists():
            shutil.copy(src, cfg_dir / name)

    # Patch CONFIG_DIR in every module that imported it by value
    monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(profile_routes_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_writer_mod, "CONFIG_DIR", cfg_dir)

    # Also redirect DB to temp so app startup migrations don't touch real data
    db_path = tmp_path / "seeker.db"
    monkeypatch.setattr("seeker_os.database._db_path", lambda: db_path)
    run_migrations(db_path)

    return cfg_dir


@pytest.fixture()
def client(temp_config):
    """Test client with config + DB pointed at temp paths."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------

class TestProfile:
    def test_get_profile(self, client):
        r = client.get("/api/profile")
        # With example profile.yml copied in, should return 200
        assert r.status_code == 200, r.text
        data = r.json()
        assert "user" in data
        assert "comp" in data
        assert "experience" in data
        assert "resume" in data

    def test_get_profile_not_found(self, tmp_path, monkeypatch):
        """When no profile.yml exists, GET /api/profile returns 404."""
        cfg_dir = tmp_path / "config_empty"
        cfg_dir.mkdir()
        monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(profile_routes_mod, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(config_writer_mod, "CONFIG_DIR", cfg_dir)
        db_path = tmp_path / "seeker.db"
        monkeypatch.setattr("seeker_os.database._db_path", lambda: db_path)
        run_migrations(db_path)
        c = TestClient(app)
        r = c.get("/api/profile")
        assert r.status_code == 404

    def test_update_profile(self, client):
        # Update the instructions field
        r = client.put("/api/profile", json={"instructions": "Test instructions from API"})
        assert r.status_code == 200
        assert "saved" in r.json()["message"].lower()

        # Verify the update persisted
        r2 = client.get("/api/profile")
        assert r2.status_code == 200
        assert r2.json()["instructions"] == "Test instructions from API"


# ---------------------------------------------------------------------------
# Filters endpoints
# ---------------------------------------------------------------------------

class TestFilters:
    def test_get_filters(self, client):
        r = client.get("/api/filters")
        assert r.status_code == 200
        data = r.json()
        assert "filters" in data
        assert "title_filters" in data
        assert "freshness_days" in data["filters"]

    def test_update_filters(self, client):
        r = client.put("/api/filters", json={"filters": {"freshness_days": 45}})
        assert r.status_code == 200
        assert "saved" in r.json()["message"].lower()

        # Verify it persisted
        r2 = client.get("/api/filters")
        assert r2.status_code == 200
        assert r2.json()["filters"]["freshness_days"] == 45


# ---------------------------------------------------------------------------
# Accuracy rules endpoints
# ---------------------------------------------------------------------------

VALID_RULES = [
    {
        "id": "test_no_expert",
        "description": "Avoid claiming 'expert'",
        "type": "disallowed_phrases",
        "phrases": ["expert in", "mastery of"],
        "severity": "medium",
    },
    {
        "id": "test_forbidden_tech",
        "description": "Never claim these technologies",
        "type": "forbidden_technologies",
        "technologies": ["cobol", "fortran"],
        "severity": "high",
    },
]


class TestAccuracyRules:
    def test_get_accuracy_rules_empty(self, tmp_path, monkeypatch):
        """No accuracy_rules.yml → empty list."""
        cfg_dir = tmp_path / "config_no_rules"
        cfg_dir.mkdir()
        # copy filters so Settings loads but no accuracy_rules.yml
        src = EXAMPLE_CONFIG_DIR / "filters.example.yml"
        if src.exists():
            shutil.copy(src, cfg_dir / "filters.yml")
        monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(profile_routes_mod, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(config_writer_mod, "CONFIG_DIR", cfg_dir)
        db_path = tmp_path / "seeker.db"
        monkeypatch.setattr("seeker_os.database._db_path", lambda: db_path)
        run_migrations(db_path)
        c = TestClient(app)
        r = c.get("/api/accuracy-rules")
        assert r.status_code == 200
        assert r.json() == {"rules": []}

    def test_put_and_get_accuracy_rules(self, client):
        # PUT valid rules
        r = client.put("/api/accuracy-rules", json={"rules": VALID_RULES})
        assert r.status_code == 200
        assert "saved" in r.json()["message"].lower()

        # GET them back
        r2 = client.get("/api/accuracy-rules")
        assert r2.status_code == 200
        rules = r2.json()["rules"]
        assert len(rules) == 2
        ids = {rule["id"] for rule in rules}
        assert ids == {"test_no_expert", "test_forbidden_tech"}

    def test_put_invalid_rule_type(self, client):
        bad_rules = [
            {
                "id": "bad_type",
                "description": "Invalid type",
                "type": "not_a_real_type",
                "severity": "medium",
            }
        ]
        r = client.put("/api/accuracy-rules", json={"rules": bad_rules})
        assert r.status_code == 422

    def test_put_invalid_severity(self, client):
        bad_rules = [
            {
                "id": "bad_sev",
                "description": "Invalid severity",
                "type": "disallowed_phrases",
                "severity": "critical",
            }
        ]
        r = client.put("/api/accuracy-rules", json={"rules": bad_rules})
        assert r.status_code == 422
