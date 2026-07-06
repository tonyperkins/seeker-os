"""Regression tests for refilter & rescore status preservation.

Verifies that user decision statuses (skipped, interested, applied, etc.)
are preserved through rescoring, regardless of score movement.  System
statuses (ready, rejected) are re-evaluated.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from seeker_os.api.jobs import _refilter_rescore_job
from seeker_os.config import (
    AutoAnalysisConfig,
    FilterConfig,
    FiltersConfig,
    ProfileConfig,
    ScoringConfig,
    TitleFilters,
)
from seeker_os.database import get_connection, run_migrations
from seeker_os.events import Actor, EventType, JobStatus


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test_refilter.db"
    run_migrations(path)
    conn = get_connection(path)
    yield conn
    conn.close()


@pytest.fixture()
def settings():
    """Minimal settings stub for _refilter_rescore_job."""
    scoring = ScoringConfig(
        post_threshold=6.0,
        max_score=10.0,
        min_score=0.0,
        verdict_caps={"APPLY": None, "CONDITIONAL": 7.0, "MONITOR": 5.0, "SKIP": 3.0},
        auto_analysis=AutoAnalysisConfig(),
    )

    s = MagicMock()
    s.scoring = scoring
    s.profile = MagicMock()
    s.profile.blacklist = []
    s.profile.defense_blocklist = []
    s.profile.comp = MagicMock()
    s.profile.comp.floor = 100000
    s.filters = MagicMock()
    s.filters.filters = MagicMock()
    s.filters.filters.remote_only = False
    s.filters.filters.us_only = False
    s.filters.filters.freshness_days = 0
    s.filters.filters.comp_sanity_max = 10000000
    s.filters.filters.comp_unknown_passes = True
    s.filters.filters.comp_floor_margin_pct = 0
    s.filters.filters.seniority_floor = []
    s.filters.filters.seniority_reject = []
    s.filters.filters.seniority_unknown_passes = True
    s.filters.filters.seniority_title_override = []
    s.filters.filters.junior_title_patterns = []
    s.filters.filters.commitment_required = None
    s.filters.filters.visa_sponsorship_required = False
    s.filters.filters.location_exclude = []
    s.filters.title_filters = MagicMock()
    s.filters.title_filters.positive = []
    s.filters.title_filters.negative = []
    s.identity = None
    return s


def _insert_job(db, status="ready", score=8.0, title="Senior SRE", company="TestCo"):
    """Insert a job row and return its id."""
    cursor = db.execute(
        """
        INSERT INTO jobs (title, company, status, score, jd_full,
                          discovered_at, source_id, source_job_id,
                          workplace_type, seniority_level, comp_max,
                          core_title, workplace_countries, commitment,
                          technical_tools, comp_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title, company, status, score, "A long enough JD text for scoring.",
            "2026-01-01T00:00:00+00:00", "test", "test-1",
            "Remote", "Senior", 160000,
            title, "[]", "[]",
            "[]", "none",
        ),
    )
    db.commit()
    return cursor.lastrowid


def _row_for(db, job_id):
    return db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


class TestDecisionStatusPreservation:
    """Decision statuses must be preserved through rescoring."""

    @pytest.mark.parametrize("decision_status", [
        JobStatus.SKIPPED,
        JobStatus.INTERESTED,
        JobStatus.REVIEWING,
        JobStatus.APPLIED,
        JobStatus.ENGAGED,
        JobStatus.CAPPED,
    ])
    def test_decision_status_preserved_on_rescore(self, db, settings, decision_status):
        """A job in a decision status stays in that status after rescore,
        even if its score rises above threshold."""
        job_id = _insert_job(db, status=decision_status, score=5.0)
        row = _row_for(db, job_id)
        result = _refilter_rescore_job(db, row, settings)
        assert result.status == decision_status
        assert result.status_changed is False
        # Score is still updated
        assert result.score is not None

    def test_skipped_job_score_rises_stays_skipped(self, db, settings):
        """Regression: a skipped job whose score rises above threshold on
        rescore must stay skipped — not revert to ready."""
        job_id = _insert_job(db, status="skipped", score=5.0)
        row = _row_for(db, job_id)
        result = _refilter_rescore_job(db, row, settings)
        assert result.status == "skipped"
        assert result.status_changed is False

    def test_interested_job_stays_interested(self, db, settings):
        """Regression for the original bug: interested was not in _POST_APPLY
        or _TERMINAL, so rescore changed it to ready."""
        job_id = _insert_job(db, status="interested", score=5.0)
        row = _row_for(db, job_id)
        result = _refilter_rescore_job(db, row, settings)
        assert result.status == "interested"
        assert result.status_changed is False


class TestSystemStatusReEvaluation:
    """System statuses (ready, rejected) are re-evaluated by rescore."""

    @patch("seeker_os.scoring.engine.score_job")
    def test_ready_job_stays_ready_when_score_above_threshold(self, mock_score, db, settings):
        from seeker_os.scoring.engine import ScoreResult
        mock_score.return_value = ScoreResult(score=8.0, reasons=[], gaps=[], fired_modifiers={})
        job_id = _insert_job(db, status="ready", score=8.0)
        row = _row_for(db, job_id)
        result = _refilter_rescore_job(db, row, settings)
        assert result.status == "ready"

    @patch("seeker_os.scoring.engine.score_job")
    def test_system_rejected_can_become_ready(self, mock_score, db, settings):
        """A system-rejected job (no candidate rejection event) can be
        re-evaluated to ready if its score is above threshold."""
        from seeker_os.scoring.engine import ScoreResult
        mock_score.return_value = ScoreResult(score=8.0, reasons=[], gaps=[], fired_modifiers={})
        job_id = _insert_job(db, status="rejected", score=8.0)
        row = _row_for(db, job_id)
        result = _refilter_rescore_job(db, row, settings)
        assert result.status == "ready"
        assert result.status_changed is True


class TestCandidateRejectionPreservation:
    """Candidate-rejected jobs (manual rejection) are preserved — they are
    user decisions, not system rejections."""

    def test_candidate_rejected_stays_rejected(self, db, settings):
        """A job rejected by the candidate (not system) must be preserved."""
        from seeker_os.events import record_event, transition_status

        job_id = _insert_job(db, status="ready", score=8.0)
        # Simulate a candidate rejection
        transition_status(
            db, job_id, "rejected", EventType.REJECTED, Actor.CANDIDATE,
            metadata={"reason": "tech_stack_mismatch"},
        )
        db.commit()

        row = _row_for(db, job_id)
        result = _refilter_rescore_job(db, row, settings)
        assert result.status == "rejected"
        assert result.status_changed is False
