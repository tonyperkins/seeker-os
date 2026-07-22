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


class TestIdentityInjection:
    """Task 2: identity rules are injected into the JD analyzer prompt."""

    @patch("seeker_os.llm.router.ModelRouter")
    def test_identity_text_injected_into_prompt(self, mock_router_cls, db_path):
        from seeker_os.analysis.jd_analyzer import analyze_job

        job_id = _insert_job(db_path)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo", "title": "SRE", "url": "",
                "verdict": "APPLY", "weighted_score": 7.0,
                "one_line": "Good.", "named_gaps": [], "hard_blockers": [],
                "rubric_breakdown": [], "bonuses_applied": [], "penalties_applied": [],
                "comp": {"posted": None, "meets_floor": None, "note": ""},
                "positioning": {"aligned": True, "note": ""},
                "company_fit": {"size_bucket": None, "stage": None, "remote_policy": None, "note": ""},
                "tailoring": {"lead_with": [], "reframe_summary": "", "do_not_claim": []},
                "red_flags": [], "confidence": 0.8,
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        # Create a mock settings with identity configured
        from seeker_os.config import IdentityConfig, ExperienceAnchor, HonestQualifier
        settings = MagicMock()
        settings.profile = None
        settings.scoring = None
        settings.identity = IdentityConfig(
            positioning="I build reliable systems, not design products",
            experience_anchor=ExperienceAnchor(
                phrase="NN+ years in engineering",
                applies_to="overall career",
            ),
            honest_qualifiers=[
                HonestQualifier(skill="Rust", framing="learning, not production"),
            ],
            never_claim=["Blockchain"],
        )

        analyze_job(settings, job_id)

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        # Identity text should be injected
        assert "I build reliable systems" in user_prompt
        assert "NN+ years in engineering" in user_prompt
        assert "Rust" in user_prompt
        assert "Blockchain" in user_prompt
        # The IDENTITY section header should be present
        assert "IDENTITY" in user_prompt

    @patch("seeker_os.llm.router.ModelRouter")
    def test_no_identity_section_when_not_configured(self, mock_router_cls, db_path):
        from seeker_os.analysis.jd_analyzer import analyze_job

        job_id = _insert_job(db_path)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo", "title": "SRE", "url": "",
                "verdict": "APPLY", "weighted_score": 7.0,
                "one_line": "Good.", "named_gaps": [], "hard_blockers": [],
                "rubric_breakdown": [], "bonuses_applied": [], "penalties_applied": [],
                "comp": {"posted": None, "meets_floor": None, "note": ""},
                "positioning": {"aligned": True, "note": ""},
                "company_fit": {"size_bucket": None, "stage": None, "remote_policy": None, "note": ""},
                "tailoring": {"lead_with": [], "reframe_summary": "", "do_not_claim": []},
                "red_flags": [], "confidence": 0.8,
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        settings = MagicMock()
        settings.profile = None
        settings.scoring = None
        settings.identity = None

        analyze_job(settings, job_id)

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        # Should have the placeholder text, not a crash
        assert "no identity rules configured" in user_prompt


class TestHybridAcceptedCitiesInjection:
    """Verify hybrid_accepted_cities from filters.yml is injected into the
    analysis prompt so the LLM doesn't falsely flag local hybrid jobs as
    remote_policy_conflict hard blockers."""

    @patch("seeker_os.llm.router.ModelRouter")
    def test_hybrid_cities_in_prompt(self, mock_router_cls, db_path):
        from seeker_os.analysis.jd_analyzer import analyze_job
        from seeker_os.config import (
            FilterConfig, FiltersConfig, TitleFilters,
            LocationPrefs, CompPrefs, ExperiencePrefs, EmploymentPrefs,
            ProfileConfig, UserIdentity, ResumePrefs, CrossReferencePrefs,
        )

        job_id = _insert_job(db_path)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo", "title": "SRE", "url": "",
                "verdict": "APPLY", "weighted_score": 7.0,
                "one_line": "Good.", "named_gaps": [], "hard_blockers": [],
                "rubric_breakdown": [], "bonuses_applied": [], "penalties_applied": [],
                "comp": {"posted": None, "meets_floor": None, "note": ""},
                "positioning": {"aligned": True, "note": ""},
                "company_fit": {"size_bucket": None, "stage": None, "remote_policy": None, "note": ""},
                "tailoring": {"lead_with": [], "reframe_summary": "", "do_not_claim": []},
                "red_flags": [], "confidence": 0.8,
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        settings = MagicMock()
        settings.config_dir = db_path.parent
        settings.profile = ProfileConfig(
            user=UserIdentity(name="Test", email="t@t.com", location="Leander, TX"),
            location=LocationPrefs(
                remote_only=True,
                accepted_cities=["austin", "leander"],
                accepted_states=["tx"],
            ),
            comp=CompPrefs(floor=170000, target=200000, stretch=250000),
            experience=ExperiencePrefs(years=25, anchor_phrase="25+ years"),
            employment=EmploymentPrefs(commitment="Full Time", role_type="IC"),
            resume=ResumePrefs(
                master_path="data/master_resume.md",
                accuracy_rules_path="config/accuracy_rules.yml",
                output_dir="data/resumes",
            ),
            cross_reference=CrossReferencePrefs(repo_path="~/projects/test"),
        )
        settings.scoring = None
        settings.identity = None
        settings.filters = FiltersConfig(
            filters=FilterConfig(
                remote_only=True,
                us_only=True,
                hybrid_accepted_cities=["austin", "leander", "cedar park"],
            ),
            title_filters=TitleFilters(),
        )

        analyze_job(settings, job_id)

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        # The hybrid accepted cities must appear in the prompt
        assert "hybrid accepted in:" in user_prompt
        assert "austin" in user_prompt
        assert "leander" in user_prompt
        assert "cedar park" in user_prompt

    @patch("seeker_os.llm.router.ModelRouter")
    def test_no_hybrid_cities_when_empty(self, mock_router_cls, db_path):
        from seeker_os.analysis.jd_analyzer import analyze_job
        from seeker_os.config import (
            FilterConfig, FiltersConfig, TitleFilters,
            LocationPrefs, CompPrefs, ExperiencePrefs, EmploymentPrefs,
            ProfileConfig, UserIdentity, ResumePrefs, CrossReferencePrefs,
        )

        job_id = _insert_job(db_path)

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo", "title": "SRE", "url": "",
                "verdict": "APPLY", "weighted_score": 7.0,
                "one_line": "Good.", "named_gaps": [], "hard_blockers": [],
                "rubric_breakdown": [], "bonuses_applied": [], "penalties_applied": [],
                "comp": {"posted": None, "meets_floor": None, "note": ""},
                "positioning": {"aligned": True, "note": ""},
                "company_fit": {"size_bucket": None, "stage": None, "remote_policy": None, "note": ""},
                "tailoring": {"lead_with": [], "reframe_summary": "", "do_not_claim": []},
                "red_flags": [], "confidence": 0.8,
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        settings = MagicMock()
        settings.config_dir = db_path.parent
        settings.profile = ProfileConfig(
            user=UserIdentity(name="Test", email="t@t.com", location="Leander, TX"),
            location=LocationPrefs(remote_only=True, accepted_cities=[]),
            comp=CompPrefs(floor=170000, target=200000, stretch=250000),
            experience=ExperiencePrefs(years=25, anchor_phrase="25+ years"),
            employment=EmploymentPrefs(commitment="Full Time", role_type="IC"),
            resume=ResumePrefs(
                master_path="data/master_resume.md",
                accuracy_rules_path="config/accuracy_rules.yml",
                output_dir="data/resumes",
            ),
            cross_reference=CrossReferencePrefs(repo_path="~/projects/test"),
        )
        settings.scoring = None
        settings.identity = None
        settings.filters = FiltersConfig(
            filters=FilterConfig(remote_only=True, us_only=True, hybrid_accepted_cities=[]),
            title_filters=TitleFilters(),
        )

        analyze_job(settings, job_id)

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        # Should NOT contain hybrid accepted cities annotation
        assert "hybrid accepted in:" not in user_prompt
