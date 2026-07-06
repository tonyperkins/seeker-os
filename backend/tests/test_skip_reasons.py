"""Tests for skip-reason capture — event payload shape, calibration report
pickup, and the annotate-skip endpoint.

Covers:
1. Skip endpoint writes reason+details into application_events metadata
2. Reject endpoint writes reason+details into application_events metadata
3. Calibration report picks up skip reasons in skip_reason_summary
4. Calibration report skip_no_reason counts reasonless skips
5. Annotate-skip endpoint adds reason to existing event metadata
6. No-reason-skips endpoint lists jobs missing reasons
"""

import json

import pytest
from fastapi.testclient import TestClient

from seeker_os.database import get_connection, run_migrations, json_decode
from seeker_os.events import Actor, EventType, record_event, transition_status


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "skip_reasons.db"
    run_migrations(path)
    conn = get_connection(path)
    yield conn
    conn.close()


@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    """TestClient wired to the temp DB."""
    import seeker_os.api.jobs as jobs_module
    from seeker_os.api.app import app

    db_path = tmp_path / "skip_reasons.db"
    monkeypatch.setattr(
        jobs_module, "get_connection", lambda: get_connection(db_path)
    )
    return TestClient(app)


def insert_job(db, title="Senior SRE", company="TestCo", status="ready"):
    cursor = db.execute(
        """INSERT INTO jobs (title, company, status, discovered_at)
           VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00')""",
        (title, company, status),
    )
    db.commit()
    return cursor.lastrowid


class TestSkipEndpointPayload:
    """Verify the skip endpoint writes reason+details into event metadata."""

    def test_skip_with_reason_and_details(self, db, client):
        job_id = insert_job(db)
        r = client.post(f"/api/jobs/{job_id}/skip", json={
            "reason": "tech_stack_mismatch",
            "details": "Heavy on Java, I'm Python/Go",
        })
        assert r.status_code == 200

        event_row = db.execute(
            "SELECT metadata FROM application_events "
            "WHERE job_id = ? AND event_type = 'skipped'",
            (job_id,),
        ).fetchone()
        metadata = json_decode(event_row["metadata"])
        assert metadata["reason"] == "tech_stack_mismatch"
        assert metadata["details"] == "Heavy on Java, I'm Python/Go"

        job_row = db.execute(
            "SELECT reject_reason FROM jobs WHERE id = ?", (job_id,),
        ).fetchone()
        assert job_row["reject_reason"] == "tech_stack_mismatch"

    def test_skip_without_reason(self, db, client):
        job_id = insert_job(db)
        r = client.post(f"/api/jobs/{job_id}/skip")
        assert r.status_code == 200

        row = db.execute(
            "SELECT metadata FROM application_events "
            "WHERE job_id = ? AND event_type = 'skipped'",
            (job_id,),
        ).fetchone()
        assert row["metadata"] is None

        job_row = db.execute(
            "SELECT reject_reason FROM jobs WHERE id = ?", (job_id,),
        ).fetchone()
        assert job_row["reject_reason"] is None

    def test_skip_with_reason_only(self, db, client):
        job_id = insert_job(db)
        r = client.post(f"/api/jobs/{job_id}/skip", json={"reason": "comp"})
        assert r.status_code == 200

        row = db.execute(
            "SELECT metadata FROM application_events "
            "WHERE job_id = ? AND event_type = 'skipped'",
            (job_id,),
        ).fetchone()
        metadata = json_decode(row["metadata"])
        assert metadata["reason"] == "comp"
        assert "details" not in metadata


class TestRejectEndpointPayload:
    """Verify the reject endpoint writes reason+details into event metadata."""

    def test_reject_with_reason_and_details(self, db, client):
        job_id = insert_job(db)
        r = client.post(f"/api/jobs/{job_id}/reject", json={
            "reason": "location_rto",
            "details": "4 days onsite",
        })
        assert r.status_code == 200

        row = db.execute(
            "SELECT metadata FROM application_events "
            "WHERE job_id = ? AND event_type = 'rejected'",
            (job_id,),
        ).fetchone()
        metadata = json_decode(row["metadata"])
        assert metadata["reason"] == "location_rto"
        assert metadata["details"] == "4 days onsite"


class TestCalibrationReportSkipReasons:
    """Verify the calibration report picks up skip reasons."""

    def test_skip_reason_summary_counts(self, db):
        from seeker_os.config import CalibrationConfig, ScoringConfig
        from seeker_os.scoring.calibration import build_calibration_report

        rubric = ScoringConfig(
            post_threshold=6.0,
            calibration=CalibrationConfig(bucket_width=1.0),
        )

        j1 = _insert_scored_job(db, net_score=8.0)
        j2 = _insert_scored_job(db, net_score=7.0)
        j3 = _insert_scored_job(db, net_score=3.0)
        j4 = _insert_scored_job(db, net_score=5.0)

        _skip_with_reason(db, j1, "tech_stack_mismatch")
        _skip_with_reason(db, j2, "tech_stack_mismatch")
        _skip_with_reason(db, j3, "comp")
        _skip_with_reason(db, j4)  # no reason

        report = build_calibration_report(db, rubric)
        assert report["skip_reason_summary"]["tech_stack_mismatch"] == 2
        assert report["skip_reason_summary"]["comp"] == 1
        assert report["skip_no_reason"] == 1
        assert report["total_skipped"] == 4

    def test_no_skips_means_empty_summary(self, db):
        from seeker_os.config import CalibrationConfig, ScoringConfig
        from seeker_os.scoring.calibration import build_calibration_report

        rubric = ScoringConfig(
            post_threshold=6.0,
            calibration=CalibrationConfig(bucket_width=1.0),
        )
        _insert_scored_job(db, net_score=7.0)

        report = build_calibration_report(db, rubric)
        assert report["skip_reason_summary"] == {}
        assert report["skip_no_reason"] == 0

    def test_rejected_events_count_as_skipped_with_reason(self, db):
        from seeker_os.config import CalibrationConfig, ScoringConfig
        from seeker_os.scoring.calibration import build_calibration_report

        rubric = ScoringConfig(
            post_threshold=6.0,
            calibration=CalibrationConfig(bucket_width=1.0),
        )
        j1 = _insert_scored_job(db, net_score=8.0)
        record_event(
            db, j1, EventType.REJECTED, Actor.CANDIDATE,
            metadata={"reason": "domain_mismatch"},
        )
        db.commit()

        report = build_calibration_report(db, rubric)
        assert report["skip_reason_summary"]["domain_mismatch"] == 1
        assert report["skip_no_reason"] == 0


class TestAnnotateSkipEndpoint:
    """Verify the annotate-skip endpoint adds reason to existing events."""

    def test_annotate_adds_reason_to_skip(self, db, client):
        job_id = insert_job(db)
        # Skip without reason
        client.post(f"/api/jobs/{job_id}/skip")

        # Verify no reason
        row = db.execute(
            "SELECT metadata FROM application_events WHERE job_id = ? AND event_type = 'skipped'",
            (job_id,),
        ).fetchone()
        assert row["metadata"] is None

        # Annotate
        r = client.post(f"/api/jobs/{job_id}/annotate-skip", json={
            "reason": "company_size",
            "details": "Too large for my preference",
        })
        assert r.status_code == 200

        row = db.execute(
            "SELECT metadata FROM application_events "
            "WHERE job_id = ? AND event_type = 'skipped'",
            (job_id,),
        ).fetchone()
        metadata = json_decode(row["metadata"])
        assert metadata["reason"] == "company_size"
        assert metadata["details"] == "Too large for my preference"

        job_row = db.execute(
            "SELECT reject_reason FROM jobs WHERE id = ?", (job_id,),
        ).fetchone()
        assert job_row["reject_reason"] == "company_size"

    def test_annotate_no_skip_event_returns_404(self, db, client):
        job_id = insert_job(db)
        r = client.post(f"/api/jobs/{job_id}/annotate-skip", json={"reason": "comp"})
        assert r.status_code == 404

    def test_annotate_job_not_found_returns_404(self, db, client):
        r = client.post("/api/jobs/99999/annotate-skip", json={"reason": "comp"})
        assert r.status_code == 404

    def test_annotate_updates_reject_reason_column(self, db, client):
        job_id = insert_job(db)
        client.post(f"/api/jobs/{job_id}/skip")
        client.post(f"/api/jobs/{job_id}/annotate-skip", json={"reason": "not_interested"})

        row = db.execute(
            "SELECT reject_reason FROM jobs WHERE id = ?", (job_id,),
        ).fetchone()
        assert row["reject_reason"] == "not_interested"


class TestNoReasonSkipsEndpoint:
    """Verify the no-reason-skips listing endpoint."""

    def test_lists_skips_without_reason(self, db, client):
        j1 = insert_job(db)
        j2 = insert_job(db)
        j3 = insert_job(db)

        # j1: skip without reason
        client.post(f"/api/jobs/{j1}/skip")
        # j2: skip with reason
        client.post(f"/api/jobs/{j2}/skip", json={"reason": "comp"})
        # j3: reject without reason
        client.post(f"/api/jobs/{j3}/reject", json={"reason": "other"})

        r = client.get("/api/jobs/skipped/no-reason")
        assert r.status_code == 200
        items = r.json()
        job_ids = [item["job_id"] for item in items]
        assert j1 in job_ids
        assert j2 not in job_ids
        assert j3 not in job_ids

    def test_empty_when_all_have_reasons(self, db, client):
        j1 = insert_job(db)
        client.post(f"/api/jobs/{j1}/skip", json={"reason": "comp"})

        r = client.get("/api/jobs/skipped/no-reason")
        assert r.status_code == 200
        assert r.json() == []

    def test_includes_job_metadata(self, db, client):
        j1 = insert_job(db, title="DevOps Engineer", company="AcmeCorp")
        client.post(f"/api/jobs/{j1}/skip")

        r = client.get("/api/jobs/skipped/no-reason")
        items = r.json()
        item = next(i for i in items if i["job_id"] == j1)
        assert item["title"] == "DevOps Engineer"
        assert item["company"] == "AcmeCorp"
        assert item["status"] == "skipped"
        assert item["event_type"] == "skipped"
        assert "event_id" in item
        assert "occurred_at" in item


# --- Helpers ---

def _insert_scored_job(db, net_score, title="Senior SRE", company="TestCo"):
    cursor = db.execute(
        """INSERT INTO jobs (title, company, status, net_score, score,
                              discovered_at)
           VALUES (?, ?, 'ready', ?, ?, '2026-01-01T00:00:00+00:00')""",
        (title, company, net_score, net_score),
    )
    db.commit()
    return cursor.lastrowid


def _skip_with_reason(db, job_id, reason=None):
    metadata = {"reason": reason} if reason else None
    record_event(
        db, job_id, EventType.SKIPPED, Actor.CANDIDATE,
        metadata=metadata,
    )
    db.commit()
