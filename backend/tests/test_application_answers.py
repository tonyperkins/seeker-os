"""Tests for application answer generation with ai_policy enforcement.

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
    path = tmp_path / "test_answers.db"
    run_migrations(path)

    _orig = dbmod.get_connection

    def _get_connection(_p=path):
        return _orig(_p)

    monkeypatch.setattr(dbmod, "get_connection", _get_connection)
    monkeypatch.setattr("seeker_os.application_answers.generator.get_connection", _get_connection)
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
        "comp": {"floor": 100000, "target": 120000, "stretch": 160000},
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

    # Write accuracy_rules.yml with traceability disabled
    (test_config / "accuracy_rules.yml").write_text(
        yaml.dump({"rules": [], "traceability": {"enabled": False}}, default_flow_style=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
    settings = Settings()
    settings.config_dir = test_config
    return settings


class TestApplicationAnswerAIPolicy:
    @patch("seeker_os.application_answers.generator.ModelRouter")
    def test_forbidden_policy_returns_refusal(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='forbidden' → returns refusal, does not call LLM."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="forbidden")

        from seeker_os.application_answers.generator import generate_application_answer

        result = generate_application_answer(settings, job_id, "Describe your experience with Kubernetes.")

        assert result["refused"] is True
        assert "forbidden" in result["refusal_reason"]
        assert result["answer_text"] == ""
        # LLM must NOT have been called
        mock_router_cls.assert_not_called()

    @patch("seeker_os.application_answers.generator.ModelRouter")
    def test_forbidden_allows_critique(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='forbidden' still allows critique of user-supplied draft."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="forbidden")

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="Feedback: Your draft mentions Kubernetes but the master resume doesn't mention it.",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.application_answers.generator import critique_application_answer

        result = critique_application_answer(
            settings, job_id, "Describe your experience with Kubernetes.",
            "I have extensive Kubernetes experience.",
        )

        assert "critique" in result
        assert result["critique"] != ""
        # LLM WAS called for critique (critique is allowed even when forbidden)
        mock_router_cls.assert_called_once()

    @patch("seeker_os.application_answers.generator.ModelRouter")
    def test_draft_only_clean_content(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='draft_only' → is_draft=True, but content is clean (no notice embedded)."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="draft_only")

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="I have 5 years of Go experience and built CI/CD pipelines.",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.application_answers.generator import generate_application_answer
        import sqlite3

        result = generate_application_answer(settings, job_id, "Describe your CI/CD experience.")

        assert result.get("refused", False) is False
        assert result["is_draft"] is True
        assert result["draft_notice"] != ""

        # Check the DB row — content must be clean
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT answer_text FROM application_answers WHERE id = ?",
            (result["answer_id"],),
        ).fetchone()
        conn.close()
        db_content = row["answer_text"]

        # DB content must be clean — no draft notice text
        assert "DRAFT" not in db_content
        assert "rewrite in your own words" not in db_content.lower()
        assert db_content == "I have 5 years of Go experience and built CI/CD pipelines."

        # The markdown file has an HTML comment header (out-of-band)
        saved = Path(result["markdown_path"]).read_text()
        assert "<!-- DRAFT:" in saved
        # But the actual content after the comment is clean
        assert "I have 5 years of Go" in saved

    @patch("seeker_os.application_answers.generator.ModelRouter")
    def test_allowed_generates_normally(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='allowed' → generates normally, no draft label."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="allowed")

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="I have 5 years of Go experience and built CI/CD pipelines.",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.application_answers.generator import generate_application_answer

        result = generate_application_answer(settings, job_id, "Describe your CI/CD experience.")

        assert result.get("refused", False) is False
        assert result["is_draft"] is False
        assert result["answer_id"] is not None

    @patch("seeker_os.application_answers.generator.ModelRouter")
    def test_null_policy_generates_normally(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy=null → generates normally."""
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy=None)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="I have 5 years of Go experience.",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.application_answers.generator import generate_application_answer

        result = generate_application_answer(settings, job_id, "Describe your experience.")

        assert result.get("refused", False) is False
        assert result["is_draft"] is False

    @patch("seeker_os.application_answers.generator.ModelRouter")
    def test_forbidden_critique_returns_no_authored_content(self, mock_router_cls, db_path, tmp_path, monkeypatch):
        """ai_policy='forbidden' => critique returns observations only, no authored answer text.

        This pins the structural guarantee: under forbidden policy, the critique path
        returns a 'critique' field with feedback, and does NOT populate any answer_text
        or content field with generated prose that a user could paste as an answer.
        """
        settings = _make_settings(tmp_path, monkeypatch)
        job_id = _insert_job(db_path, ai_policy="forbidden")

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=(
                "## Critique\n\n"
                "1. The draft claims 'expert in Kubernetes' but the master resume says "
                "'currently ramping, intermediate level'. This is overstated.\n"
                "2. No specific workloads mentioned. Add detail about Acme Corp production workloads.\n"
                "3. Consider mentioning the SRE/deployment layer scope to set honest expectations."
            ),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        from seeker_os.application_answers.generator import critique_application_answer

        result = critique_application_answer(
            settings, job_id,
            question="Describe your Kubernetes experience.",
            user_draft="I am an expert in Kubernetes and can do anything with it.",
        )

        # The critique field must be populated with feedback text
        assert "critique" in result
        assert result["critique"] != ""
        assert "overstated" in result["critique"].lower()

        # The critique result must NOT contain any answer_text / answer field
        # — the critique path is observation-only, not authoring.
        assert "answer_text" not in result, (
            "critique_application_answer must not return answer_text — "
            "that would be authored content under forbidden policy"
        )
        assert "answer" not in result, (
            "critique_application_answer must not return an 'answer' field — "
            "that would be authored content under forbidden policy"
        )

        # The result must not contain any field that looks like generated answer content
        # (other than the critique itself)
        content_fields = [k for k in result.keys() if "text" in k.lower() and k != "critique"]
        assert content_fields == [], (
            f"critique_application_answer returned content-like fields {content_fields} — "
            f"forbidden policy must not produce authored content"
        )
