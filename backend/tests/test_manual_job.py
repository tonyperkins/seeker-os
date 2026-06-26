"""Tests for manual job entry, dedup handling, filter bypass, and override audit trail."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection, DB_PATH


@pytest.fixture(scope="module")
def client():
    """Create a test client. DB migrations run on startup."""
    run_migrations()
    # Clean up any leftover test manual jobs from previous runs
    db = get_connection()
    try:
        manual_ids = db.execute("SELECT id FROM jobs WHERE source_id='manual' AND discovered_query='manual'").fetchall()
        if manual_ids:
            id_list = [str(r["id"]) for r in manual_ids]
            id_csv = ",".join(id_list)
            for table in ["dedup_registry", "resumes", "company_research", "job_analyses", "cover_letters", "application_answers", "application_events"]:
                db.execute(f"DELETE FROM {table} WHERE job_id IN ({id_csv})")
            db.execute(f"DELETE FROM jobs WHERE id IN ({id_csv})")
        db.commit()
    finally:
        db.close()
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def cleanup_after():
    """Clean up test manual jobs after all tests in the module complete."""
    yield
    db = get_connection()
    try:
        manual_ids = db.execute("SELECT id FROM jobs WHERE source_id='manual' AND discovered_query='manual'").fetchall()
        if manual_ids:
            id_list = [str(r["id"]) for r in manual_ids]
            id_csv = ",".join(id_list)
            for table in ["dedup_registry", "resumes", "company_research", "job_analyses", "cover_letters", "application_answers", "application_events"]:
                db.execute(f"DELETE FROM {table} WHERE job_id IN ({id_csv})")
            db.execute(f"DELETE FROM jobs WHERE id IN ({id_csv})")
        db.commit()
    finally:
        db.close()


# Long JD text that passes the evidence gate (>500 chars)
_LONG_JD = (
    "We are looking for a Senior Site Reliability Engineer to join our platform team. "
    "You will be responsible for designing, building, and operating the infrastructure "
    "that powers our distributed systems. This includes Kubernetes cluster management, "
    "Terraform infrastructure as code, CI/CD pipeline development, observability with "
    "Prometheus and Grafana, and incident response. The ideal candidate has 5+ years "
    "of experience with cloud platforms (AWS or GCP), strong programming skills in "
    "Python or Go, and deep knowledge of distributed systems. You will work closely "
    "with engineering teams to ensure reliability, scalability, and performance of "
    "our services. This is a fully remote position open to candidates in the United "
    "States. We offer competitive compensation, equity, and comprehensive benefits."
) * 3  # ~1800 chars — well above the 500 char evidence gate


class TestManualJobCreate:
    """POST /api/jobs — manual job creation with paste-JD path."""

    def test_create_with_pasted_jd(self, client):
        """Paste-JD path: provide url + jd_text, job is created and scored."""
        unique_jd = "First test ZZZ000\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/sre-test-1",
            "title": "Senior SRE",
            "company": "TestCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"] is not None
        assert data["job"]["source_id"] == "manual"
        assert data["job"]["discovered_query"] == "manual"
        assert data["job"]["status"] == "ready"
        assert data["job"]["tier_passed"] == 4
        assert data["job"]["jd_fetch_status"] == "fetched"
        assert data["job"]["score"] is not None
        assert data["job"]["jd_full"] == unique_jd.strip()

    def test_create_dedup_url_hash(self, client):
        """Same URL twice → second request returns already_exists."""
        url = "https://example.com/jobs/dedup-test-1"
        unique_jd = "Unique dedup test ABC123-XYZ789\n\n" + _LONG_JD
        # First create
        r1 = client.post("/api/jobs", json={
            "url": url,
            "title": "DevOps Engineer",
            "company": "DedupCo",
            "location": "Remote, US",
            "jd_text": unique_jd,
        })
        assert r1.status_code == 200
        assert r1.json()["status"] == "created"
        job_id = r1.json()["job"]["id"]

        # Second attempt with same URL
        r2 = client.post("/api/jobs", json={
            "url": url,
            "title": "Different Title",
            "company": "DifferentCo",
            "jd_text": "Different content DEF456\n\n" + _LONG_JD,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "already_exists"
        assert data["existing_job_id"] == job_id
        assert data["job"] is None  # no job created

    def test_create_fetch_failed_no_insert(self, client):
        """When JD fetch fails (no jd_text), no job is inserted."""
        r = client.post("/api/jobs", json={
            "url": "https://nonexistent.invalid/jobs/no-such-page",
            "title": "Test Job",
            "company": "FetchFailCo",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "fetch_failed"
        assert data["job"] is None
        assert data["fetch_error"] is not None

        # Verify no job was inserted
        db = get_connection()
        try:
            row = db.execute(
                "SELECT id FROM jobs WHERE company = 'FetchFailCo'"
            ).fetchone()
            assert row is None, "No job should be inserted on fetch failure"
        finally:
            db.close()

    def test_manual_job_bypasses_filters(self, client):
        """Manual job that would fail hard filters still lands in 'ready' with warnings."""
        # This job has no remote/workplace_type — would fail remote_only filter
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/filter-bypass-test",
            "title": "On-site Engineer",
            "company": "OnSiteCo",
            "location": "New York, NY",
            "workplace_type": "On-Site",
            "jd_text": "Filter bypass GHI789\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"]["status"] == "ready"  # NOT rejected
        # Filter warnings should be recorded
        assert len(data["filter_warnings"]) > 0
        assert data["job"]["filter_warnings"] == data["filter_warnings"]

    def test_manual_job_low_score_not_rejected(self, client):
        """Manual job with a low score still lands in 'ready' — user decides."""
        # Use a title/company that won't match any scoring patterns → low score
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/low-score-test",
            "title": "Sales Representative",
            "company": "SalesCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Low score JKL012\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"]["status"] == "ready"  # NOT rejected even with low score
        assert data["job"]["score"] is not None

    def test_source_filter(self, client):
        """List jobs with source=manual filter."""
        # First create a manual job
        client.post("/api/jobs", json={
            "url": "https://example.com/jobs/source-filter-test",
            "title": "Platform Engineer",
            "company": "FilterTestCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Source filter MNO345\n\n" + _LONG_JD,
        })

        r = client.get("/api/jobs?source=manual&limit=10")
        assert r.status_code == 200
        for job in r.json():
            assert job["source_id"] == "manual" if "source_id" in job else True

    def test_content_hash_soft_dup_no_force(self, client):
        """Same JD content, different URL → possible_duplicate, NO insert."""
        shared_jd = "Soft dup content HASHTEST999\n\n" + _LONG_JD
        # First create
        r1 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/content-dup-original",
            "title": "Backend Engineer",
            "company": "ContentDupCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": shared_jd,
        })
        assert r1.status_code == 200
        assert r1.json()["status"] == "created"
        original_id = r1.json()["job"]["id"]

        # Second attempt: different URL, same JD content
        r2 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/content-dup-second",
            "title": "Backend Engineer",
            "company": "ContentDupCo",
            "jd_text": shared_jd,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "possible_duplicate"
        assert data["existing_job_id"] == original_id
        assert data["existing_summary"] is not None
        assert data["job"] is None  # no job created

        # Verify no second row was inserted
        db = get_connection()
        try:
            dup_rows = db.execute(
                "SELECT id FROM jobs WHERE company = 'ContentDupCo'"
            ).fetchall()
            assert len(dup_rows) == 1, "Should be exactly 1 row — the original"
        finally:
            db.close()

    def test_content_hash_soft_dup_with_force(self, client):
        """Same JD content, different URL, force=True → inserts as likely_duplicate."""
        shared_jd = "Force dup content HASHTEST888\n\n" + _LONG_JD
        # First create
        r1 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/force-dup-original",
            "title": "Frontend Engineer",
            "company": "ForceDupCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": shared_jd,
        })
        assert r1.json()["status"] == "created"
        original_id = r1.json()["job"]["id"]

        # Second attempt: force=True
        r2 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/force-dup-second",
            "title": "Frontend Engineer",
            "company": "ForceDupCo",
            "jd_text": shared_jd,
            "force": True,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "likely_duplicate"
        assert data["existing_job_id"] == original_id
        assert data["job"] is not None  # job WAS created
        assert data["job"]["status"] == "ready"

    def test_url_hash_dupe_not_forceable(self, client):
        """Exact url_hash dupe returns already_exists even with force=True."""
        url = "https://example.com/jobs/exact-dup-not-forceable"
        jd = "Exact dup not forceable AAA111\n\n" + _LONG_JD
        r1 = client.post("/api/jobs", json={
            "url": url,
            "title": "Engineer",
            "company": "ExactDupCo",
            "jd_text": jd,
        })
        assert r1.json()["status"] == "created"

        r2 = client.post("/api/jobs", json={
            "url": url,
            "jd_text": jd,
            "force": True,
        })
        assert r2.json()["status"] == "already_exists"
        assert r2.json()["job"] is None

    def test_paste_retry_after_fetch_fail(self, client):
        """Fetch fails → no insert; re-submit same request with jd_text → inserts."""
        url = "https://nonexistent.invalid/jobs/paste-retry-test"
        # First attempt: no jd_text, fetch will fail
        r1 = client.post("/api/jobs", json={
            "url": url,
            "title": "Paste Retry Engineer",
            "company": "PasteRetryCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
        })
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["status"] == "fetch_failed"
        assert data1["job"] is None

        # Verify no row inserted
        db = get_connection()
        try:
            row = db.execute(
                "SELECT id FROM jobs WHERE company = 'PasteRetryCo'"
            ).fetchone()
            assert row is None
        finally:
            db.close()

        # Re-submit with jd_text — same URL, now with pasted JD
        r2 = client.post("/api/jobs", json={
            "url": url,
            "title": "Paste Retry Engineer",
            "company": "PasteRetryCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Paste retry content BBB222\n\n" + _LONG_JD,
        })
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["status"] == "created"
        assert data2["job"] is not None
        assert data2["job"]["status"] == "ready"
        assert data2["job"]["score"] is not None
        assert data2["job"]["company"] == "PasteRetryCo"

    def test_research_cache_reuse(self, client):
        """Manual job at a cached company uses the cached dossier (no new research call)
        and gets a research-adjusted score."""
        from seeker_os.dedup.normalize import normalize_company

        company_name = "ResearchCacheCo"
        company_norm = normalize_company(company_name)

        # Seed a cached company dossier with high enough confidence to not be a stub
        # and a funding section with a recent layoff to trigger the recent_layoffs modifier.
        funding_data = {
            "founded": 2015,
            "stage": "Series B",
            "layoffs": [{"date": datetime.now(timezone.utc).isoformat(), "pct": 10.0}],
            "financial_health": "stable",
            "confidence": 0.8,
        }
        sentiment_data = {
            "overall_rating_estimate": 3.5,
            "confidence": 0.7,
        }
        now_iso = datetime.now(timezone.utc).isoformat()

        db = get_connection()
        try:
            db.execute(
                """INSERT INTO company_research (
                    job_id, company_name, company_norm, funding_data, sentiment_data,
                    overall_confidence, researched_at, created_at,
                    retrieval_sources
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_name,
                    company_norm,
                    json.dumps(funding_data),
                    json.dumps(sentiment_data),
                    0.8,
                    now_iso,
                    now_iso,
                    json.dumps(["https://example.com/source1"]),
                ),
            )
            db.commit()
        finally:
            db.close()

        # Create a manual job at this company
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/research-cache-test",
            "title": "Senior SRE",
            "company": company_name,
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Research cache test CCC333\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"] is not None
        assert data["job"]["score"] is not None

        job_id = data["job"]["id"]

        # Verify research-adjusted score was computed (not None, not equal to base score)
        db = get_connection()
        try:
            row = db.execute(
                "SELECT score, research_adjusted_score, research_delta, research_breakdown FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            assert row is not None
            base_score = row["score"]
            adjusted = row["research_adjusted_score"]
            delta = row["research_delta"]
            breakdown = row["research_breakdown"]

            # The research path should have run — adjusted score should be set
            assert adjusted is not None, "research_adjusted_score should be set (cache hit)"
            assert delta is not None and delta != 0, (
                f"research_delta should be non-zero (layoff modifier should apply), got {delta}"
            )
            # The recent_layoffs modifier is -1.5, so delta should be -1.5
            assert delta == -1.5, f"Expected -1.5 (recent_layoffs), got {delta}"
            # Adjusted score should be base + delta
            assert adjusted == base_score + delta, (
                f"adjusted ({adjusted}) should be base ({base_score}) + delta ({delta})"
            )
            # Breakdown should contain the recent_layoffs factor
            breakdown_list = json.loads(breakdown) if breakdown else []
            factors = [item["factor"] for item in breakdown_list]
            assert "recent_layoffs" in factors, (
                f"breakdown should include recent_layoffs, got {factors}"
            )

            # Prove no new retrieval call was made: the _try_apply_research_adjustment
            # path is cache-hit-only (SQL lookup, no Tavily/retrieval). Verify only
            # the one row we seeded exists — no second row was inserted.
            cr_rows = db.execute(
                "SELECT id FROM company_research WHERE company_norm = ?",
                (company_norm,),
            ).fetchall()
            assert len(cr_rows) == 1, (
                f"Expected exactly 1 company_research row (the seeded cache), "
                f"got {len(cr_rows)} — a new retrieval call may have been made"
            )
        finally:
            db.close()

        # Clean up the seeded dossier
        db = get_connection()
        try:
            db.execute("DELETE FROM company_research WHERE company_name = ?", (company_name,))
            db.commit()
        finally:
            db.close()


class TestJobOverride:
    """POST /api/jobs/{id}/override — auditable override of rejected jobs."""

    def test_override_preserves_audit_trail(self, client):
        """Override records timestamp, note, and original reject reason."""
        # Create a manual job (lands in ready)
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/override-test",
            "title": "Senior SRE",
            "company": "OverrideCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Override test PQR678\n\n" + _LONG_JD,
        })
        job_id = r.json()["job"]["id"]

        # Reject it
        client.post(f"/api/jobs/{job_id}/reject", json={"reason": "score below threshold"})

        # Verify it's rejected
        r2 = client.get(f"/api/jobs/{job_id}")
        assert r2.json()["status"] == "rejected"
        assert r2.json()["reject_reason"] == "score below threshold"

        # Override
        r3 = client.post(f"/api/jobs/{job_id}/override", json={
            "note": "Want to apply anyway — good company",
            "target_status": "ready",
        })
        assert r3.status_code == 200

        # Verify audit trail
        r4 = client.get(f"/api/jobs/{job_id}")
        detail = r4.json()
        assert detail["status"] == "ready"
        assert detail["overridden_at"] is not None
        assert detail["override_note"] == "Want to apply anyway — good company"
        assert detail["original_reject_reason"] == "score below threshold"
        # Score is still visible (not overwritten)
        assert detail["score"] is not None

    def test_override_only_rejected(self, client):
        """Override fails on non-rejected jobs."""
        # Create a manual job (lands in ready)
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/override-non-rejected",
            "title": "DevOps Engineer",
            "company": "NonRejectCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Non-reject STU901\n\n" + _LONG_JD,
        })
        job_id = r.json()["job"]["id"]

        # Try to override a ready job → should fail
        r2 = client.post(f"/api/jobs/{job_id}/override", json={"note": "test"})
        assert r2.status_code == 400

    def test_override_not_found(self, client):
        """Override on nonexistent job returns 404."""
        r = client.post("/api/jobs/99999/override", json={"note": "test"})
        assert r.status_code == 404

    def test_delete_job(self, client):
        """Delete removes the job and all dependent records."""
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/delete-test",
            "title": "Delete Me",
            "company": "DeleteCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Delete test VWX123\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        job_id = r.json()["job"]["id"]

        # Delete it
        r2 = client.delete(f"/api/jobs/{job_id}")
        assert r2.status_code == 200

        # Confirm it's gone
        r3 = client.get(f"/api/jobs/{job_id}")
        assert r3.status_code == 404

    def test_delete_not_found(self, client):
        """Delete on nonexistent job returns 404."""
        r = client.delete("/api/jobs/99999")
        assert r.status_code == 404
