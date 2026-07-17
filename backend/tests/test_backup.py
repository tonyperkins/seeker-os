"""Tests for backup/restore API endpoints."""

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("STATIC_OUT_DIR", "/nonexistent")

import seeker_os.api.backup as backupmod
import seeker_os.database as dbmod
from seeker_os.api.app import app
from seeker_os.database import run_migrations, MIGRATIONS


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    run_migrations(db_path)

    _orig_db_path = dbmod._db_path
    _orig_get_connection = dbmod.get_connection
    _orig_backup_db_path = backupmod._db_path
    dbmod._db_path = lambda: db_path
    backupmod._db_path = lambda: db_path

    def _temp_get_connection(_db_path=None):
        return _orig_get_connection(db_path)

    dbmod.get_connection = _temp_get_connection
    yield TestClient(app)
    dbmod._db_path = _orig_db_path
    dbmod.get_connection = _orig_get_connection
    backupmod._db_path = _orig_backup_db_path


class TestBackupExcludeSecrets:
    """SEC-C: .env is excluded from default backups, included with include_secrets=true."""

    def test_default_backup_excludes_env(self, client):
        """Default backup zip should not contain .env."""
        r = client.get("/api/backup")
        assert r.status_code == 200
        buf = io.BytesIO(r.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        assert ".env" not in names
        assert "_manifest.json" in names

    def test_backup_with_secrets_includes_env(self, client):
        """Backup with include_secrets=true should contain .env if it exists."""
        # .env may or may not exist on the test machine; just verify the param is accepted
        r = client.get("/api/backup", params={"include_secrets": "true"})
        assert r.status_code == 200
        buf = io.BytesIO(r.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        # If .env exists at project root, it should be in the zip
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            assert ".env" in names

    def test_restore_without_env_succeeds(self, client, tmp_path):
        """A backup zip that does NOT contain .env should restore cleanly —
        missing .env is tolerated, not an error."""
        # Create a minimal zip with just a config file, no .env
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("_manifest.json", '{"files": ["config/test.yml"], "timestamp": "2025-01-01T00:00:00Z"}')
            zf.writestr("config/test.yml", "test: value\n")
        buf.seek(0)

        r = client.post(
            "/api/backup/restore",
            files={"file": ("test-backup.zip", buf.getvalue(), "application/zip")},
        )
        assert r.status_code == 200
        data = r.json()
        assert "config/test.yml" in data["restored"]
        # No error about missing .env


class TestDbRestoreVersionCheck:
    """Step 6: Reject DB restore if user_version > len(MIGRATIONS), allow if equal."""

    def test_current_version_db_not_rejected(self, client, tmp_path):
        """A DB with user_version == len(MIGRATIONS) should be accepted (not rejected)."""
        import sqlite3

        # Create a valid SQLite DB at the current schema version
        db_path = tmp_path / "test_current.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = %d" % len(MIGRATIONS))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        db_bytes = db_path.read_bytes()
        r = client.post(
            "/api/backup/db/restore",
            files={"file": ("test.db", db_bytes, "application/octet-stream")},
        )
        # Should succeed — current version is allowed
        assert r.status_code == 200
        assert "restored" in r.json().get("message", "").lower() or r.json().get("ok") is True

    def test_future_version_db_rejected(self, client, tmp_path):
        """A DB with user_version beyond the pre-squash range should be rejected."""
        import sqlite3
        from seeker_os.database import _PRE_SQUASH_HIGH_WATER_MARK

        db_path = tmp_path / "test_future.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = %d" % (_PRE_SQUASH_HIGH_WATER_MARK + 1))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        db_bytes = db_path.read_bytes()
        r = client.post(
            "/api/backup/db/restore",
            files={"file": ("test.db", db_bytes, "application/octet-stream")},
        )
        assert r.status_code == 400
        assert "newer" in r.json()["detail"].lower()
