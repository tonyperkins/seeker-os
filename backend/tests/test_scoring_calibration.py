"""Tests for the scoring calibration report — decision derivation, score
buckets, miss lists, and per-modifier precision.

Runs against an isolated temp DB (not the live seeker.db) so fixtures with
known outcomes are exact.
"""

import json

import pytest
from fastapi.testclient import TestClient

from seeker_os.config import CalibrationConfig, ModifierRule, ScoringConfig
from seeker_os.database import get_connection, run_migrations
from seeker_os.events import Actor, EventType, record_event
from seeker_os.scoring.calibration import build_calibration_report, derive_decisions


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "calibration.db"
    run_migrations(path)
    conn = get_connection(path)
    yield conn
    conn.close()


@pytest.fixture()
def rubric():
    return ScoringConfig(
        post_threshold=6.0,
        positive_modifiers=[
            ModifierRule(signal="aws", pattern="aws", points=1.0, check="jd"),
            ModifierRule(signal="terraform", pattern="terraform", points=1.0, check="jd"),
        ],
        negative_modifiers=[
            ModifierRule(signal="oncall", pattern="on.?call", points=-1.0, check="jd"),
        ],
    )


def insert_job(
    db,
    title="Senior SRE",
    company="TestCo",
    score=None,
    research_adjusted_score=None,
    net_score=None,
    analysis_verdict=None,
    score_reasons=None,
    score_modifiers=None,
    research_breakdown=None,
):
    cursor = db.execute(
        """
        INSERT INTO jobs (title, company, score, research_adjusted_score, net_score,
                          analysis_verdict, score_reasons, score_modifiers,
                          research_breakdown, discovered_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00+00:00', 'ready')
        """,
        (
            title, company, score, research_adjusted_score, net_score,
            analysis_verdict,
            json.dumps(score_reasons) if score_reasons is not None else None,
            json.dumps(score_modifiers) if score_modifiers is not None else None,
            json.dumps(research_breakdown) if research_breakdown is not None else None,
        ),
    )
    db.commit()
    return cursor.lastrowid


def apply_to(db, job_id):
    record_event(db, job_id, EventType.APPLIED, Actor.CANDIDATE)
    db.commit()


def skip(db, job_id, event_type=EventType.SKIPPED, reason=None):
    record_event(
        db, job_id, event_type, Actor.CANDIDATE,
        metadata={"reason": reason} if reason else None,
    )
    db.commit()


class TestDeriveDecisions:
    def test_empty_event_log(self, db):
        insert_job(db, net_score=7.0)
        assert derive_decisions(db) == {}

    def test_applied_and_skipped(self, db):
        applied_id = insert_job(db, net_score=7.0)
        skipped_id = insert_job(db, net_score=7.0)
        rejected_id = insert_job(db, net_score=7.0)
        apply_to(db, applied_id)
        skip(db, skipped_id)
        skip(db, rejected_id, event_type=EventType.REJECTED, reason="too corporate")

        decisions = derive_decisions(db)
        assert decisions[applied_id]["decision"] == "applied"
        assert decisions[skipped_id]["decision"] == "skipped"
        assert decisions[rejected_id]["decision"] == "skipped"
        assert decisions[rejected_id]["reason"] == "too corporate"

    def test_apply_wins_over_skip(self, db):
        """Skip-then-apply (or apply-then-skip) counts as applied."""
        job_id = insert_job(db, net_score=7.0)
        skip(db, job_id)
        apply_to(db, job_id)
        assert derive_decisions(db)[job_id]["decision"] == "applied"

    def test_system_events_are_not_decisions(self, db):
        """Pipeline scored_rejected / system events don't count as user decisions."""
        job_id = insert_job(db, net_score=2.0)
        record_event(db, job_id, EventType.SCORED_REJECTED, Actor.SYSTEM)
        db.commit()
        assert derive_decisions(db) == {}


class TestEmptyEventLog:
    def test_all_ignored_no_misses(self, db, rubric):
        insert_job(db, net_score=8.0)
        insert_job(db, net_score=3.0)
        report = build_calibration_report(db, rubric)

        assert report["total_scored"] == 2
        assert report["total_applied"] == 0
        assert report["total_skipped"] == 0
        assert report["total_ignored"] == 2
        assert report["false_positives"] == []
        assert report["false_negatives"] == []

    def test_empty_database(self, db, rubric):
        report = build_calibration_report(db, rubric)
        assert report["total_scored"] == 0
        assert report["buckets"] == []
        assert report["modifier_precision"] == []


class TestNoAnalysisFallback:
    def test_net_score_falls_back_to_adjusted_then_base(self, db, rubric):
        insert_job(db, net_score=None, research_adjusted_score=7.5, score=6.0)
        insert_job(db, net_score=None, research_adjusted_score=None, score=4.0)
        report = build_calibration_report(db, rubric)

        assert report["total_scored"] == 2
        labels = {b["bucket"]: b["total"] for b in report["buckets"] if b["total"]}
        assert labels == {"4–5": 1, "7–8": 1}

    def test_job_with_no_scores_is_unscored(self, db, rubric):
        insert_job(db)  # no score at all (never reached tier 4)
        insert_job(db, net_score=6.5)
        report = build_calibration_report(db, rubric)
        assert report["total_unscored"] == 1
        assert report["total_scored"] == 1

    def test_miss_entry_verdict_none_without_analysis(self, db, rubric):
        job_id = insert_job(db, net_score=8.0, analysis_verdict=None)
        skip(db, job_id)
        report = build_calibration_report(db, rubric)
        assert report["false_positives"][0]["job_id"] == job_id
        assert report["false_positives"][0]["analysis_verdict"] is None


class TestDegenerateCases:
    def test_all_applied(self, db, rubric):
        high_id = insert_job(db, net_score=8.0)
        low_id = insert_job(db, net_score=3.0)
        apply_to(db, high_id)
        apply_to(db, low_id)
        report = build_calibration_report(db, rubric)

        assert report["total_applied"] == 2
        assert report["total_skipped"] == 0
        for bucket in report["buckets"]:
            if bucket["total"]:
                assert bucket["applied_pct"] == 100.0
        # Low-scored apply is a false negative; no false positives possible
        assert [m["job_id"] for m in report["false_negatives"]] == [low_id]
        assert report["false_positives"] == []

    def test_all_skipped(self, db, rubric):
        high_id = insert_job(db, net_score=8.0)
        low_id = insert_job(db, net_score=3.0)
        skip(db, high_id, reason="bad glassdoor reviews")
        skip(db, low_id)
        report = build_calibration_report(db, rubric)

        assert report["total_skipped"] == 2
        assert report["total_applied"] == 0
        for bucket in report["buckets"]:
            if bucket["total"]:
                assert bucket["skipped_pct"] == 100.0
        # High-scored skip is a false positive; no false negatives possible
        assert [m["job_id"] for m in report["false_positives"]] == [high_id]
        assert report["false_positives"][0]["decision_reason"] == "bad glassdoor reviews"
        assert report["false_negatives"] == []


class TestBuckets:
    def test_bucket_edges_and_contiguity(self, db, rubric):
        insert_job(db, net_score=6.0)   # exactly on the edge → 6–7 bucket
        insert_job(db, net_score=6.99)  # same bucket
        insert_job(db, net_score=3.5)   # 3–4 bucket
        report = build_calibration_report(db, rubric)

        by_label = {b["bucket"]: b for b in report["buckets"]}
        # Contiguous range 3–7, including empty 4–5 and 5–6 buckets
        assert list(by_label) == ["3–4", "4–5", "5–6", "6–7"]
        assert by_label["6–7"]["total"] == 2
        assert by_label["3–4"]["total"] == 1
        assert by_label["4–5"]["total"] == 0

    def test_bucket_width_from_config(self, db):
        rubric = ScoringConfig(calibration=CalibrationConfig(bucket_width=2.0))
        insert_job(db, net_score=7.0)
        report = build_calibration_report(db, rubric)
        assert report["bucket_width"] == 2.0
        assert report["buckets"][0]["bucket"] == "6–8"

    def test_bucket_width_override(self, db, rubric):
        insert_job(db, net_score=7.25)
        report = build_calibration_report(db, rubric, bucket_width=0.5)
        assert report["buckets"][0]["bucket"] == "7–7.5"

    def test_invalid_bucket_width_rejected(self, db, rubric):
        with pytest.raises(ValueError):
            build_calibration_report(db, rubric, bucket_width=0)


class TestMissThresholds:
    def test_thresholds_default_to_post_threshold(self, db, rubric):
        report = build_calibration_report(db, rubric)
        assert report["high_score_threshold"] == rubric.post_threshold
        assert report["low_score_threshold"] == rubric.post_threshold

    def test_config_thresholds_override_post_threshold(self, db):
        rubric = ScoringConfig(
            post_threshold=6.0,
            calibration=CalibrationConfig(
                high_score_threshold=8.0, low_score_threshold=4.0
            ),
        )
        borderline_skip = insert_job(db, net_score=7.0)   # < 8 → not a false positive
        real_fp = insert_job(db, net_score=8.5)
        borderline_apply = insert_job(db, net_score=5.0)  # >= 4 → not a false negative
        real_fn = insert_job(db, net_score=3.0)
        skip(db, borderline_skip)
        skip(db, real_fp)
        apply_to(db, borderline_apply)
        apply_to(db, real_fn)

        report = build_calibration_report(db, rubric)
        assert [m["job_id"] for m in report["false_positives"]] == [real_fp]
        assert [m["job_id"] for m in report["false_negatives"]] == [real_fn]

    def test_miss_entry_is_inspectable(self, db, rubric):
        job_id = insert_job(
            db,
            net_score=7.0,
            score=8.0,
            research_adjusted_score=7.0,
            analysis_verdict="CONDITIONAL",
            score_reasons=["Base: Senior SRE/Platform/Infra (4.0)", "+1.0 aws"],
            score_modifiers={"aws": 1.0, "oncall": -1.0},
            research_breakdown=[
                {"factor": "recent_layoffs", "delta": -1.5, "confidence": 0.7,
                 "source_section": "funding"},
            ],
        )
        skip(db, job_id)
        miss = build_calibration_report(db, rubric)["false_positives"][0]

        assert miss["base_score_label"] == "Senior SRE/Platform/Infra (4.0)"
        assert miss["positive_modifiers"] == {"aws": 1.0}
        assert miss["negative_modifiers"] == {"oncall": -1.0}
        assert miss["research_factors"][0]["factor"] == "recent_layoffs"
        assert miss["analysis_verdict"] == "CONDITIONAL"
        assert miss["base_score"] == 8.0

    def test_false_positive_ordering(self, db, rubric):
        mid = insert_job(db, net_score=7.0)
        top = insert_job(db, net_score=9.0)
        skip(db, mid)
        skip(db, top)
        report = build_calibration_report(db, rubric)
        # Worst misses (highest score skipped) first
        assert [m["job_id"] for m in report["false_positives"]] == [top, mid]


class TestModifierPrecision:
    def test_known_outcomes(self, db, rubric):
        """Fixture with known outcomes: aws fires on 4 jobs — 2 applied,
        1 skipped, 1 ignored → precision 0.5, decided_precision 2/3."""
        a1 = insert_job(db, net_score=7.0, score_modifiers={"aws": 1.0})
        a2 = insert_job(db, net_score=7.0, score_modifiers={"aws": 1.0, "oncall": -1.0})
        s1 = insert_job(db, net_score=7.0, score_modifiers={"aws": 1.0})
        insert_job(db, net_score=7.0, score_modifiers={"aws": 1.0})  # ignored
        apply_to(db, a1)
        apply_to(db, a2)
        skip(db, s1)

        report = build_calibration_report(db, rubric)
        by_signal = {m["signal"]: m for m in report["modifier_precision"]}

        aws = by_signal["aws"]
        assert aws["fired"] == 4
        assert aws["applied"] == 2
        assert aws["skipped"] == 1
        assert aws["ignored"] == 1
        assert aws["precision"] == pytest.approx(0.5)
        assert aws["decided_precision"] == pytest.approx(2 / 3)
        assert aws["in_rubric"] is True

        oncall = by_signal["oncall"]
        assert oncall["fired"] == 1
        assert oncall["applied"] == 1
        assert oncall["precision"] == pytest.approx(1.0)

        # terraform never fired → not reported
        assert "terraform" not in by_signal

    def test_signal_not_in_rubric_flagged(self, db, rubric):
        """A signal that fired historically but was renamed/removed from the
        rubric still shows up, flagged in_rubric=False."""
        job_id = insert_job(db, net_score=7.0, score_modifiers={"old_signal": 0.5})
        apply_to(db, job_id)
        report = build_calibration_report(db, rubric)
        by_signal = {m["signal"]: m for m in report["modifier_precision"]}
        assert by_signal["old_signal"]["in_rubric"] is False

    def test_decided_precision_none_when_all_ignored(self, db, rubric):
        insert_job(db, net_score=7.0, score_modifiers={"aws": 1.0})
        report = build_calibration_report(db, rubric)
        aws = report["modifier_precision"][0]
        assert aws["precision"] == 0.0
        assert aws["decided_precision"] is None


class TestCalibrationEndpoint:
    @pytest.fixture()
    def client(self, db, tmp_path, monkeypatch, rubric):
        import seeker_os.api.analytics as analytics_module
        from seeker_os.api.app import app

        db_path = tmp_path / "calibration.db"
        monkeypatch.setattr(
            analytics_module, "get_connection", lambda: get_connection(db_path)
        )

        class _StubSettings:
            scoring = rubric

        monkeypatch.setattr(analytics_module, "get_settings", lambda: _StubSettings())
        return TestClient(app)

    def test_endpoint_returns_report(self, db, client):
        job_id = insert_job(db, net_score=8.0, score_modifiers={"aws": 1.0})
        skip(db, job_id)

        r = client.get("/api/analytics/calibration")
        assert r.status_code == 200
        body = r.json()
        assert body["bucket_width"] == 1.0
        assert body["total_scored"] == 1
        assert body["false_positives"][0]["job_id"] == job_id
        assert body["modifier_precision"][0]["signal"] == "aws"

    def test_endpoint_bucket_width_param(self, db, client):
        insert_job(db, net_score=7.25)
        r = client.get("/api/analytics/calibration", params={"bucket_width": 0.5})
        assert r.status_code == 200
        assert r.json()["buckets"][0]["bucket"] == "7–7.5"

    def test_endpoint_rejects_bad_bucket_width(self, client):
        r = client.get("/api/analytics/calibration", params={"bucket_width": 0})
        assert r.status_code == 422
