"""Tests for the JD analyzer module.

Covers server-timestamp enforcement (Task 1) and score independence (Task 4).
Does NOT call a real LLM — the ModelRouter is mocked.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import seeker_os.database as dbmod
from seeker_os.database import run_migrations


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Create a temp SQLite DB and patch get_connection to use it."""
    path = tmp_path / "test_jd.db"
    run_migrations(path)

    _orig = dbmod.get_connection

    def _get_connection(_p=path):
        return _orig(_p)

    monkeypatch.setattr(dbmod, "get_connection", _get_connection)
    monkeypatch.setattr("seeker_os.analysis.jd_analyzer.get_connection", _get_connection)
    return path


def _insert_job(path: Path, jd_full: str = "Test JD text") -> int:
    conn = sqlite3.connect(str(path))
    cur = conn.execute(
        "INSERT INTO jobs (title, company, status, jd_full) VALUES (?, ?, ?, ?)",
        ("SRE", "TestCo", "ready", jd_full),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


class TestServerTimestamp:
    """Task 1: analyzed_at must be server-generated, not model-emitted."""

    @patch("seeker_os.llm.router.ModelRouter")
    def test_analyzed_at_uses_server_time(self, mock_router_cls, db_path):
        from seeker_os.analysis.jd_analyzer import analyze_job

        bogus_date = "1999-01-01T00:00:00Z"
        job_id = _insert_job(db_path)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo",
                "title": "SRE",
                "url": "https://example.com",
                "analyzed_at": bogus_date,
                "verdict": "APPLY",
                "weighted_score": 8.0,
                "one_line": "Good fit.",
                "named_gaps": [],
                "hard_blockers": [],
                "rubric_breakdown": [],
                "bonuses_applied": [],
                "penalties_applied": [],
                "comp": {"posted": None, "meets_floor": None, "note": ""},
                "positioning": {"aligned": True, "note": ""},
                "company_fit": {"size_bucket": None, "stage": None, "remote_policy": None, "note": ""},
                "tailoring": {"lead_with": [], "reframe_summary": "", "do_not_claim": []},
                "red_flags": [],
                "confidence": 0.8,
            }),
            provider="test",
            model="test-model",
            input_tokens=100,
            output_tokens=200,
            latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        settings = MagicMock()
        settings.profile = None
        settings.scoring = None
        before = datetime.now(timezone.utc).isoformat()
        result = analyze_job(settings, job_id)
        after = datetime.now(timezone.utc).isoformat()

        # The DB-stored analyzed_at must NOT be the bogus date
        assert result.get("analyzed_at") != bogus_date

        # Verify the DB row has server time, not the model's value
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT analyzed_at FROM job_analyses WHERE job_id = ?", (job_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["analyzed_at"] != bogus_date
        assert before <= row["analyzed_at"] <= after


class TestScoreIndependence:
    """Task 4: verify the precomputed score is NOT injected into the prompt."""

    @patch("seeker_os.llm.router.ModelRouter")
    def test_score_not_in_prompt(self, mock_router_cls, db_path):
        from seeker_os.analysis.jd_analyzer import analyze_job

        job_id = _insert_job(db_path)

        # Insert a score into the job row
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE jobs SET score = 9.5 WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo",
                "title": "SRE",
                "url": "https://example.com",
                "verdict": "APPLY",
                "weighted_score": 7.0,
                "one_line": "Good.",
                "named_gaps": [],
                "hard_blockers": [],
                "rubric_breakdown": [],
                "bonuses_applied": [],
                "penalties_applied": [],
                "comp": {"posted": None, "meets_floor": None, "note": ""},
                "positioning": {"aligned": True, "note": ""},
                "company_fit": {"size_bucket": None, "stage": None, "remote_policy": None, "note": ""},
                "tailoring": {"lead_with": [], "reframe_summary": "", "do_not_claim": []},
                "red_flags": [],
                "confidence": 0.8,
            }),
            provider="test",
            model="test-model",
            input_tokens=100,
            output_tokens=200,
            latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        settings = MagicMock()
        settings.profile = None
        settings.scoring = None
        analyze_job(settings, job_id)

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        # The precomputed score (9.5) must NOT appear in the prompt
        assert "9.5" not in user_prompt
