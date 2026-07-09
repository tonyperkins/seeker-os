"""Tests for the FastAPI API endpoints."""

import pytest
from fastapi.testclient import TestClient

import seeker_os.database as dbmod
from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Create a test client with DB isolated to a temp path."""
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    run_migrations(db_path)

    _orig_db_path = dbmod._db_path
    _orig_get_connection = dbmod.get_connection
    dbmod._db_path = lambda: db_path

    def _temp_get_connection(_db_path=None):
        return _orig_get_connection(db_path)

    dbmod.get_connection = _temp_get_connection
    yield TestClient(app)
    dbmod._db_path = _orig_db_path
    dbmod.get_connection = _orig_get_connection


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Seeker OS API"


class TestJobs:
    def test_list_jobs(self, client):
        r = client.get("/api/jobs?limit=5")
        assert r.status_code == 200
        data = r.json()
        assert "jobs" in data
        assert "total" in data
        assert isinstance(data["jobs"], list)

    def test_list_jobs_filter_status(self, client):
        r = client.get("/api/jobs?status=ready&limit=10")
        assert r.status_code == 200
        for job in r.json()["jobs"]:
            assert job["status"] == "ready"

    def test_list_jobs_min_score(self, client):
        r = client.get("/api/jobs?min_score=6.0&limit=10")
        assert r.status_code == 200
        for job in r.json()["jobs"]:
            if job["score"] is not None:
                assert job["score"] >= 6.0

    def test_list_jobs_sort_by_net_score(self, client):
        """Ready jobs should sort by net_score DESC by default, and sort_by param works."""
        # Default sort for ready jobs should be net_score (COALESCE fallback to score)
        r = client.get("/api/jobs?status=ready&limit=10")
        assert r.status_code == 200
        jobs = r.json()["jobs"]
        for job in jobs:
            assert job["status"] == "ready"
        # Verify descending order by COALESCE(net_score, score)
        scores = [(j.get("net_score") or j.get("score") or 0) for j in jobs]
        assert scores == sorted(scores, reverse=True)

    def test_list_jobs_sort_by_score_explicit(self, client):
        """Explicit sort_by=score should sort by raw score DESC."""
        r = client.get("/api/jobs?status=ready&sort_by=score&limit=10")
        assert r.status_code == 200
        jobs = r.json()["jobs"]
        scores = [(j.get("score") or 0) for j in jobs]
        assert scores == sorted(scores, reverse=True)

    def test_list_jobs_sort_by_net_score_explicit(self, client):
        """Explicit sort_by=net_score should sort by COALESCE(net_score, score) DESC."""
        r = client.get("/api/jobs?sort_by=net_score&limit=10")
        assert r.status_code == 200
        jobs = r.json()["jobs"]
        scores = [(j.get("net_score") or j.get("score") or 0) for j in jobs]
        assert scores == sorted(scores, reverse=True)

    def test_get_job_not_found(self, client):
        r = client.get("/api/jobs/99999")
        assert r.status_code == 404

    def test_get_job_detail(self, client):
        # First get a job ID from the list
        r = client.get("/api/jobs?limit=1")
        jobs = r.json()["jobs"]
        if jobs:
            job_id = jobs[0]["id"]
            r2 = client.get(f"/api/jobs/{job_id}")
            assert r2.status_code == 200
            detail = r2.json()
            assert detail["id"] == job_id
            assert "title" in detail
            assert "company" in detail

    def test_reject_job(self, client):
        # Get a ready job
        r = client.get("/api/jobs?status=ready&limit=1")
        jobs = r.json()["jobs"]
        if jobs:
            job_id = jobs[0]["id"]
            r2 = client.post(f"/api/jobs/{job_id}/reject", json={"reason": "Test rejection"})
            assert r2.status_code == 200
            # Verify status changed
            r3 = client.get(f"/api/jobs/{job_id}")
            assert r3.json()["status"] == "rejected"
            # Restore it
            client.patch(f"/api/jobs/{job_id}", json={"status": "ready"})

    def test_update_job_status(self, client):
        r = client.get("/api/jobs?limit=1")
        jobs = r.json()["jobs"]
        if jobs:
            job_id = jobs[0]["id"]
            original_status = jobs[0]["status"]
            r2 = client.patch(f"/api/jobs/{job_id}", json={"status": "reviewing"})
            assert r2.status_code == 200
            # Restore
            client.patch(f"/api/jobs/{job_id}", json={"status": original_status})


class TestPipeline:
    def test_list_runs(self, client):
        r = client.get("/api/pipeline/runs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_run_not_found(self, client):
        r = client.get("/api/pipeline/runs/nonexistent")
        assert r.status_code == 404

    def test_dry_run(self, client):
        r = client.post("/api/pipeline/run", json={"dry_run": True, "tiers": [1]})
        assert r.status_code == 200
        data = r.json()
        assert "run_id" in data
        assert "cards_fetched" in data


class TestQueries:
    def test_list_queries(self, client):
        r = client.get("/api/queries")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_and_delete_query(self, client):
        # Create
        r = client.post("/api/queries", json={
            "slug": "test-query-delete-me",
            "label": "Test Query",
        })
        assert r.status_code == 200

        # Find it
        r2 = client.get("/api/queries")
        test_q = [q for q in r2.json() if q["slug"] == "test-query-delete-me"]
        assert len(test_q) == 1
        qid = test_q[0]["id"]

        # Delete
        r3 = client.delete(f"/api/queries/{qid}")
        assert r3.status_code == 200

        # Verify deleted
        r4 = client.get("/api/queries")
        test_q2 = [q for q in r4.json() if q["slug"] == "test-query-delete-me"]
        assert len(test_q2) == 0

    def test_update_query(self, client):
        # Create a temp query
        client.post("/api/queries", json={
            "slug": "test-update-query",
            "label": "Before Update",
        })
        r = client.get("/api/queries")
        q = [q for q in r.json() if q["slug"] == "test-update-query"][0]

        r2 = client.patch(f"/api/queries/{q['id']}", json={"label": "After Update"})
        assert r2.status_code == 200

        r3 = client.get("/api/queries")
        q2 = [q for q in r3.json() if q["slug"] == "test-update-query"][0]
        assert q2["label"] == "After Update"

        # Cleanup
        client.delete(f"/api/queries/{q2['id']}")


class TestSettings:
    def test_get_settings(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "profile_loaded" in data
        assert "queries_count" in data


class TestAnalytics:
    def test_funnel(self, client):
        r = client.get("/api/analytics/funnel")
        assert r.status_code == 200
        data = r.json()
        assert "total_jobs" in data
        assert "by_status" in data
        assert "by_tier" in data
        assert "score_distribution" in data

    def test_response_rate(self, client):
        r = client.get("/api/analytics/response-rate")
        assert r.status_code == 200
        data = r.json()
        assert "total_applied" in data
        assert "response_rate" in data

    def test_movement(self, client):
        r = client.get("/api/analytics/movement?days=7&limit=30")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert "total" in data
        assert "rejection_count" in data
        assert "rejection_breakdown" in data
        assert isinstance(data["events"], list)
        assert data["total"] == len(data["events"])

    def test_movement_default_params(self, client):
        r = client.get("/api/analytics/movement")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert "rejection_count" in data

    def test_movement_excludes_rejections_from_rows(self, client):
        """Manual rejections and skips should not appear in the events list.
        company_rejected IS shown as a movement row (it's a company action)."""
        r = client.get("/api/analytics/movement?days=90&limit=200")
        assert r.status_code == 200
        data = r.json()
        for evt in data["events"]:
            assert evt["event_type"] not in ("rejected", "skipped")

    def test_aging(self, client):
        r = client.get("/api/analytics/aging")
        assert r.status_code == 200
        data = r.json()
        assert "buckets" in data
        assert "stale_after_days" in data
        assert isinstance(data["buckets"], list)
        for bucket in data["buckets"]:
            assert "status" in bucket
            assert "count" in bucket
            assert "avg_days" in bucket
            assert "max_days" in bucket
            assert "stale_count" in bucket

    def test_signal_quality(self, client):
        r = client.get("/api/analytics/signal-quality")
        assert r.status_code == 200
        data = r.json()
        assert "total_analyzed" in data
        assert "verdicts" in data
        assert "apply_rate" in data
        assert "skip_rate" in data
        assert "calibration_available" in data
        assert isinstance(data["verdicts"], list)

    def test_spend(self, client):
        r = client.get("/api/analytics/spend")
        assert r.status_code == 200
        data = r.json()
        assert "total_calls" in data
        assert "total_input_tokens" in data
        assert "total_output_tokens" in data
        assert "total_estimated_cost" in data
        assert "pricing_configured" in data
        assert "by_task" in data
        assert "by_model" in data
        assert "cost_per_ready" in data
        assert "cost_per_applied" in data
        assert "pricing_fetched_at" in data
        assert "pricing_stale" in data
        assert "pricing_stale_after_days" in data
        assert "route_pricing" in data
        assert isinstance(data["by_task"], list)
        assert isinstance(data["by_model"], list)

    def test_job_summary_includes_queue_fields(self, client):
        """JobSummary should include ai_policy, score_modifiers, score_reasons for action queue."""
        r = client.get("/api/jobs?limit=1")
        assert r.status_code == 200
        jobs = r.json()["jobs"]
        if jobs:
            job = jobs[0]
            assert "ai_policy" in job
            assert "score_modifiers" in job
            assert "score_reasons" in job
