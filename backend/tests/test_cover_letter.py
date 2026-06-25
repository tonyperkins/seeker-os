"""Tests for cover letter generation with ai_policy enforcement.

The ModelRouter is mocked — no real LLM calls are made.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import seeker_os.database as dbmod
from seeker_os.database import run_migrations


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Create a temp SQLite DB and patch get_connection to use it."""
    path = tmp_path / "test_cover.db"
    run_migrations(path)

    _orig = dbmod.get_connection

    def _get_connection(_p=path):
        return _orig(_p)

    monkeypatch.setattr(dbmod, "get_connection", _get_connection)
    monkeypatch.setattr("seeker_os.cover_letter.generator.get_connection", _get_connection)
    return path


def _insert_job(path: Path, ai_policy: str | None = None) -> int:
    conn = sqlite3.connect(str(path))
    cur = conn.execute(
        "INSERT INTO jobs (title, company, status, jd_full, ai_policy) VALUES (?, ?, ?, ?, ?)",
        ("SRE", "TestCo", "ready", "We need an SRE with Kubernetes experience.", ai_policy),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def _make_settings(tmp_path, monkeypatch):
    """Create settings with a master resume file."""
    import shutil
    from seeker_os.config import Settings, CONFIG_DIR

    test_config = tmp_path / "config"
    test_config.mkdir()
    for f in CONFIG_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, test_config / f.name)

    # Create a fake master resume
    master_path = tmp_path / "master_resume.md"
    master_path.write_text("# Test User\n\n5 years of Go. Built CI/CD pipelines at Acme.\n")

    # Write profile.yml pointing to the master resume
    import yaml
    profile_data = {
        "user": {"name": "Test", "email": "test@test.com", "location": "Test, ST"},
        "location": {"remote_only": True, "accepted_cities": [], "accepted_states": [], "rejected_cities": []},
        "comp": {"floor": 100000, "target": 120000, "stretch": 150000},
        "experience": {"years": 5, "anchor_phrase": "5+ years"},
        "employment": {"commitment": "Full Time", "reject_commitments": [], "role_type": "Individual Contributor", "reject_role_types": []},
        "resume": {
            "master_path": str(master_path),
            "accuracy_rules_path": str(test_config / "accuracy_rules.yml"),
            "output_dir": str(tmp_path / "output"),
        },
        "cross_reference": {"repo_path": str(tmp_path / "jobsearch"), "auto_pull": False},
    }
    (test_config / "profile.yml").write_text(
        yaml.dump(profile_data, default_flow_style=False),
        encoding="utf-8",
    )

    # Write accuracy_rules.yml
    (test_config / "accuracy_rules.yml").write_text(
        yaml.dump({"rules": [], "traceability": {"enabled": False}}, default_flow_style=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
    settings = Settings()
    settings.config_dir = test_config
    return settings


class TestCoverLetterAIPolicy:
    @patch("seeker_os.cover_letter.generator.ModelRouter")
    def test_forbidden_policy_returns_refusal(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='forbidden' → returns refusal, does not call LLM."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="forbidden")

        from seeker_os.cover_letter.generator import generate_cover_letter

        result = generate_cover_letter(settings, job_id)

        assert result["refused"] is True
        assert "forbidden" in result["refusal_reason"]
        assert result["cover_letter_text"] == ""
        # LLM must NOT have been called
        mock_router_cls.assert_not_called()

    @patch("seeker_os.cover_letter.generator.ModelRouter")
    def test_draft_only_clean_content(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='draft_only' → is_draft=True, but content is clean (no notice embedded)."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="draft_only")

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="Dear Hiring Manager,\n\nI am writing to apply...",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.cover_letter.generator import generate_cover_letter
        import sqlite3

        result = generate_cover_letter(settings, job_id)

        assert result.get("refused", False) is False
        assert result["is_draft"] is True
        assert result["draft_notice"] != ""

        # The returned content must NOT contain the draft notice
        # (cover_letter_text is not in the response dict, but the DB row has it)
        # Check the DB row
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT cover_letter_text FROM cover_letters WHERE id = ?",
            (result["cover_letter_id"],),
        ).fetchone()
        conn.close()
        db_content = row["cover_letter_text"]

        # DB content must be clean — no draft notice text
        assert "DRAFT" not in db_content
        assert "rewrite in your own words" not in db_content.lower()
        assert db_content == "Dear Hiring Manager,\n\nI am writing to apply..."

        # The markdown file has an HTML comment header (out-of-band)
        from pathlib import Path
        saved = Path(result["markdown_path"]).read_text()
        assert "<!-- DRAFT:" in saved
        # But the actual content after the comment is clean
        assert "Dear Hiring Manager" in saved

    @patch("seeker_os.cover_letter.generator.ModelRouter")
    def test_allowed_generates_normally(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='allowed' → generates normally, no draft label."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="allowed")

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="Dear Hiring Manager,\n\nI am writing to apply...",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.cover_letter.generator import generate_cover_letter

        result = generate_cover_letter(settings, job_id)

        assert result.get("refused", False) is False
        assert result["is_draft"] is False
        assert result["cover_letter_id"] is not None

    @patch("seeker_os.cover_letter.generator.ModelRouter")
    def test_null_policy_generates_normally(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy=null → generates normally (channel default applies)."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy=None)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="Dear Hiring Manager,\n\nI am writing to apply...",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.cover_letter.generator import generate_cover_letter

        result = generate_cover_letter(settings, job_id)

        assert result.get("refused", False) is False
        assert result["is_draft"] is False
