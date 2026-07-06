"""Tests for the auto-analysis policy — candidate selection, rate limiting,
verdict resync, backfill idempotency, and the disabled-by-default no-op."""

import json

import pytest
from fastapi.testclient import TestClient

from seeker_os.analysis.auto_policy import (
    count_unanalyzed_high_scorers,
    resync_verdicts_from_analyses,
    run_auto_analysis,
    select_unanalyzed_high_scorers,
)
from seeker_os.config import AutoAnalysisConfig, ScoringConfig
from seeker_os.database import get_connection, run_migrations


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "auto_analysis.db"
    run_migrations(path)
    conn = get_connection(path)
    yield conn
    conn.close()


@pytest.fixture()
def scoring():
    return ScoringConfig(
        post_threshold=6.0,
        verdict_caps={"APPLY": None, "CONDITIONAL": 7.0, "MONITOR": 5.0, "SKIP": 3.0},
        auto_analysis=AutoAnalysisConfig(enabled=True, max_per_run=10),
    )


class _StubSettings:
    def __init__(self, scoring):
        self.scoring = scoring


def insert_job(db, score=None, net_score=None, research_adjusted_score=None,
               analysis_verdict=None, jd_full="A long enough JD text.",
               research_delta=0.0, title="Senior SRE", company="TestCo",
               status="ready"):
    cursor = db.execute(
        """
        INSERT INTO jobs (title, company, score, net_score, research_adjusted_score,
                          analysis_verdict, jd_full, research_delta,
                          discovered_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00+00:00', ?)
        """,
        (title, company, score, net_score, research_adjusted_score,
         analysis_verdict, jd_full, research_delta, status),
    )
    db.commit()
    return cursor.lastrowid


def insert_analysis(db, job_id, verdict="APPLY", analyzed_at="2026-01-02T00:00:00+00:00"):
    db.execute(
        """
        INSERT INTO job_analyses (job_id, verdict, analysis_json, analyzed_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, verdict, json.dumps({"verdict": verdict}), analyzed_at, analyzed_at),
    )
    db.commit()


class TestSelection:
    def test_threshold_filtering(self, db, scoring):
        high = insert_job(db, score=8.0)
        insert_job(db, score=4.0)  # below post_threshold
        edge = insert_job(db, score=6.0)  # exactly at threshold → included
        selected = [r["id"] for r in select_unanalyzed_high_scorers(db, scoring)]
        assert set(selected) == {high, edge}

    def test_min_score_overrides_post_threshold(self, db, scoring):
        scoring.auto_analysis.min_score = 8.0
        insert_job(db, score=7.0)
        high = insert_job(db, score=8.5)
        selected = [r["id"] for r in select_unanalyzed_high_scorers(db, scoring)]
        assert selected == [high]

    def test_uses_effective_net_score_fallback(self, db, scoring):
        # net_score wins over base: base 8.0 but net capped to 3.0 → excluded
        insert_job(db, score=8.0, net_score=3.0, analysis_verdict=None)
        # research-adjusted lifts a below-threshold base over the line
        lifted = insert_job(db, score=5.5, research_adjusted_score=6.5)
        selected = [r["id"] for r in select_unanalyzed_high_scorers(db, scoring)]
        assert selected == [lifted]

    def test_already_analyzed_excluded(self, db, scoring):
        insert_job(db, score=8.0, analysis_verdict="APPLY")
        fresh = insert_job(db, score=7.0)
        selected = [r["id"] for r in select_unanalyzed_high_scorers(db, scoring)]
        assert selected == [fresh]

    def test_no_jd_excluded(self, db, scoring):
        insert_job(db, score=8.0, jd_full="")
        insert_job(db, score=8.0, jd_full=None)
        assert select_unanalyzed_high_scorers(db, scoring) == []

    def test_orphaned_analysis_row_excluded_from_llm_queue(self, db, scoring):
        """A job with an existing job_analyses row is a resync case, not an
        LLM re-analysis case."""
        orphaned = insert_job(db, score=8.0)
        insert_analysis(db, orphaned)
        assert select_unanalyzed_high_scorers(db, scoring) == []

    def test_highest_scores_first(self, db, scoring):
        mid = insert_job(db, score=7.0)
        top = insert_job(db, score=9.0)
        selected = [r["id"] for r in select_unanalyzed_high_scorers(db, scoring)]
        assert selected == [top, mid]


class TestRunAutoAnalysis:
    def test_rate_limit(self, db, scoring):
        scoring.auto_analysis.max_per_run = 2
        for i in range(5):
            insert_job(db, score=7.0 + i * 0.1)
        calls = []
        result = run_auto_analysis(
            _StubSettings(scoring), db,
            analyze_fn=lambda settings, job_id: calls.append(job_id) or {},
        )
        assert len(calls) == 2
        assert result["analyzed"] == 2
        assert result["candidates"] == 2

    def test_limit_override(self, db, scoring):
        for i in range(4):
            insert_job(db, score=7.0)
        calls = []
        run_auto_analysis(
            _StubSettings(scoring), db, limit=3,
            analyze_fn=lambda settings, job_id: calls.append(job_id) or {},
        )
        assert len(calls) == 3

    def test_failures_counted_not_raised(self, db, scoring):
        ok = insert_job(db, score=9.0)
        bad = insert_job(db, score=8.0)

        def analyze(settings, job_id):
            if job_id == bad:
                raise ValueError("no JD")
            return {}

        result = run_auto_analysis(_StubSettings(scoring), db, analyze_fn=analyze)
        assert result["analyzed"] == 1
        assert result["failed"] == 1
        assert result["job_ids"] == [ok]
        assert len(result["errors"]) == 1

    def test_no_scoring_config_is_noop(self, db):
        insert_job(db, score=9.0)
        result = run_auto_analysis(
            _StubSettings(None), db,
            analyze_fn=lambda **kw: pytest.fail("must not be called"),
        )
        assert result["analyzed"] == 0


class TestPipelineHookDisabled:
    def test_policy_disabled_is_noop(self, db, scoring):
        """The pipeline gate: disabled policy must not touch the analyzer.
        (The runner checks auto_analysis.enabled before calling run_auto_analysis;
        this asserts the config default keeps that gate closed.)"""
        assert ScoringConfig().auto_analysis.enabled is False

    def test_disabled_config_from_yaml_absence(self):
        """A rubric with no auto_analysis section parses to disabled defaults."""
        cfg = ScoringConfig(post_threshold=6.0)
        assert cfg.auto_analysis.enabled is False
        assert cfg.auto_analysis.min_score is None
        assert cfg.auto_analysis.max_per_run == 10


class TestResync:
    def test_resync_restores_verdict_and_net(self, db, scoring):
        job = insert_job(db, score=8.5, analysis_verdict=None)
        insert_analysis(db, job, verdict="CONDITIONAL")
        assert resync_verdicts_from_analyses(db, scoring) == 1

        row = db.execute(
            "SELECT analysis_verdict, net_score FROM jobs WHERE id=?", (job,)
        ).fetchone()
        assert row["analysis_verdict"] == "CONDITIONAL"
        assert row["net_score"] == 7.0  # base 8.5 capped by CONDITIONAL

    def test_resync_uses_latest_analysis(self, db, scoring):
        job = insert_job(db, score=8.0)
        insert_analysis(db, job, verdict="SKIP", analyzed_at="2026-01-01T00:00:00+00:00")
        insert_analysis(db, job, verdict="APPLY", analyzed_at="2026-02-01T00:00:00+00:00")
        resync_verdicts_from_analyses(db, scoring)
        row = db.execute("SELECT analysis_verdict FROM jobs WHERE id=?", (job,)).fetchone()
        assert row["analysis_verdict"] == "APPLY"

    def test_resync_idempotent(self, db, scoring):
        job = insert_job(db, score=8.0)
        insert_analysis(db, job)
        assert resync_verdicts_from_analyses(db, scoring) == 1
        assert resync_verdicts_from_analyses(db, scoring) == 0  # nothing left

    def test_resync_skips_jobs_with_verdict(self, db, scoring):
        job = insert_job(db, score=8.0, analysis_verdict="MONITOR")
        insert_analysis(db, job, verdict="APPLY")
        assert resync_verdicts_from_analyses(db, scoring) == 0
        row = db.execute("SELECT analysis_verdict FROM jobs WHERE id=?", (job,)).fetchone()
        assert row["analysis_verdict"] == "MONITOR"


class TestCoverageCount:
    def test_count_includes_jdless_and_orphaned(self, db, scoring):
        insert_job(db, score=8.0)                        # actionable
        insert_job(db, score=8.0, jd_full="")            # gap, not actionable
        orphaned = insert_job(db, score=8.0)
        insert_analysis(db, orphaned)                    # gap, resync case
        insert_job(db, score=8.0, analysis_verdict="APPLY")  # covered
        insert_job(db, score=4.0)                        # below threshold
        assert count_unanalyzed_high_scorers(db, scoring) == 3

    def test_calibration_report_surfaces_count(self, db, scoring):
        from seeker_os.scoring.calibration import build_calibration_report
        insert_job(db, score=8.0)
        insert_job(db, score=8.0, analysis_verdict="APPLY")
        insert_job(db, score=4.0)
        report = build_calibration_report(db, scoring)
        assert report["high_score_unanalyzed"] == 1

    def test_count_excludes_rejected_statuses(self, db, scoring):
        """Rejected and company_rejected jobs are decided-dead — they should
        not appear in the coverage count (analyzing them wastes LLM spend)."""
        insert_job(db, score=8.0)                                    # actionable
        insert_job(db, score=8.0, status="rejected")                # dead, excluded
        insert_job(db, score=8.0, status="company_rejected")        # dead, excluded
        assert count_unanalyzed_high_scorers(db, scoring) == 1

    def test_count_excludes_custom_statuses(self, db, scoring):
        """analysis_excluded_statuses is config-driven — custom list works."""
        scoring.auto_analysis.analysis_excluded_statuses = ["rejected", "archived"]
        insert_job(db, score=8.0)                                    # actionable
        insert_job(db, score=8.0, status="rejected")                # excluded
        insert_job(db, score=8.0, status="archived")                # excluded
        insert_job(db, score=8.0, status="company_rejected")        # NOT excluded (not in list)
        assert count_unanalyzed_high_scorers(db, scoring) == 2

    def test_calibration_excludes_rejected_from_unanalyzed(self, db, scoring):
        """high_score_unanalyzed in the calibration report excludes dead statuses."""
        from seeker_os.scoring.calibration import build_calibration_report
        insert_job(db, score=8.0)                                    # gap
        insert_job(db, score=8.0, status="rejected")                # dead, excluded
        insert_job(db, score=8.0, status="company_rejected")        # dead, excluded
        report = build_calibration_report(db, scoring)
        assert report["high_score_unanalyzed"] == 1

    def test_select_excludes_rejected_statuses(self, db, scoring):
        """Candidate selection must not pick rejected jobs for LLM analysis."""
        actionable = insert_job(db, score=8.0)
        insert_job(db, score=9.0, status="rejected")                # would rank first but dead
        insert_job(db, score=8.5, status="company_rejected")        # dead
        selected = [r["id"] for r in select_unanalyzed_high_scorers(db, scoring)]
        assert selected == [actionable]


class TestBackfillEndpoint:
    @pytest.fixture()
    def client(self, db, tmp_path, monkeypatch, scoring):
        import seeker_os.api.jd_analysis as jd_module
        from seeker_os.api.app import app

        db_path = tmp_path / "auto_analysis.db"

        import seeker_os.analysis.auto_policy as policy_module
        import seeker_os.database as database_module
        monkeypatch.setattr(database_module, "_db_path", lambda: db_path)

        class _Stub:
            scoring = None
        _Stub.scoring = scoring

        import seeker_os.config as config_module
        monkeypatch.setattr(config_module, "get_settings", lambda config_dir=None: _Stub())

        self._analyzed = []

        def fake_analyze(settings, job_id, **kw):
            conn = get_connection(db_path)
            conn.execute(
                "UPDATE jobs SET analysis_verdict='APPLY' WHERE id=?", (job_id,)
            )
            conn.execute(
                "INSERT INTO job_analyses (job_id, verdict, analysis_json, analyzed_at, created_at) "
                "VALUES (?, 'APPLY', '{}', '2026-03-01T00:00:00+00:00', '2026-03-01T00:00:00+00:00')",
                (job_id,),
            )
            conn.commit()
            conn.close()
            self._analyzed.append(job_id)
            return {}

        import seeker_os.analysis.jd_analyzer as analyzer_module
        monkeypatch.setattr(analyzer_module, "analyze_job", fake_analyze)
        return TestClient(app)

    def test_backfill_resync_then_analyze_then_idempotent(self, db, client):
        orphaned = insert_job(db, score=8.5)
        insert_analysis(db, orphaned, verdict="APPLY")
        fresh = insert_job(db, score=7.0)
        insert_job(db, score=4.0)  # below threshold — untouched

        r = client.post("/api/jobs/analysis/backfill")
        assert r.status_code == 200
        body = r.json()
        assert body["resynced"] == 1
        assert body["analyzed"] == 1
        assert body["job_ids"] == [fresh]
        assert body["remaining_unanalyzed"] == 0

        # Second run: everything covered — full no-op
        r2 = client.post("/api/jobs/analysis/backfill")
        body2 = r2.json()
        assert body2["resynced"] == 0
        assert body2["candidates"] == 0
        assert body2["analyzed"] == 0

    def test_backfill_respects_limit(self, db, client):
        for _ in range(5):
            insert_job(db, score=7.5)
        r = client.post("/api/jobs/analysis/backfill", json={"limit": 2})
        body = r.json()
        assert body["analyzed"] == 2
        assert body["remaining_unanalyzed"] == 3
